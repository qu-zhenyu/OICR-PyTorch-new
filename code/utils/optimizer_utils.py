import logging
import os
import numpy as np
import torch
import torch.nn.functional as F
from torch.autograd import Variable
from ..tasks.config import cfg
# import nn as mynn
from pdb import set_trace as pause

logger = logging.getLogger(__name__)


def clip_gradient(model, clip_norm):
    """Computes a gradient clipping coefficient based on gradient norm."""
    totalnorm = 0
    for p in model.parameters():
        if p.requires_grad and (p.grad is not None):
            modulenorm = p.grad.data.norm()
            totalnorm += modulenorm ** 2
    totalnorm = torch.sqrt(totalnorm).item()

    norm = (clip_norm / max(totalnorm, clip_norm))
    for p in model.parameters():
        if p.requires_grad and (p.grad is not None):
            p.grad.mul_(norm)


def decay_learning_rate(optimizer, cur_lr, decay_rate):
    """Decay learning rate"""
    new_lr = cur_lr * decay_rate
    # ratio = _get_lr_change_ratio(cur_lr, new_lr)
    ratio = 1 / decay_rate
    if ratio > cfg.SOLVER.LOG_LR_CHANGE_THRESHOLD:
        logger.info('Changing learning rate %.6f -> %.6f', cur_lr, new_lr)
    # Update learning rate, note that different parameter may have different learning rate
    for param_group in optimizer.param_groups:
        cur_lr = param_group['lr']
        new_lr = decay_rate * param_group['lr']
        param_group['lr'] = new_lr
        if cfg.SOLVER.TYPE in ['SGD']:
            if cfg.SOLVER.SCALE_MOMENTUM and cur_lr > 1e-7 and \
                    ratio > cfg.SOLVER.SCALE_MOMENTUM_THRESHOLD:
                _CorrectMomentum(optimizer, param_group['params'], new_lr / cur_lr)


def update_learning_rate(optimizer, cur_lr, new_lr):
    """Update learning rate"""
    if cur_lr != new_lr:
        ratio = _get_lr_change_ratio(cur_lr, new_lr)
        if ratio > cfg.SOLVER.LOG_LR_CHANGE_THRESHOLD:
            logger.info('Changing learning rate %.6f -> %.6f', cur_lr, new_lr)
        # Update learning rate, note that different parameter may have different learning rate
        param_keys = []
        for ind, param_group in enumerate(optimizer.param_groups):
            if ind == 1 and cfg.SOLVER.BIAS_DOUBLE_LR:  # bias params
                param_group['lr'] = new_lr * 2
            else:
                param_group['lr'] = new_lr
            param_keys += param_group['params']
        if cfg.SOLVER.TYPE in ['SGD'] and cfg.SOLVER.SCALE_MOMENTUM and cur_lr > 1e-7 and \
                ratio > cfg.SOLVER.SCALE_MOMENTUM_THRESHOLD:
            _CorrectMomentum(optimizer, param_keys, new_lr / cur_lr)


def _CorrectMomentum(optimizer, param_keys, correction):
    """The MomentumSGDUpdate op implements the update V as

        V := mu * V + lr * grad,

    where mu is the momentum factor, lr is the learning rate, and grad is
    the stochastic gradient. Since V is not defined independently of the
    learning rate (as it should ideally be), when the learning rate is
    changed we should scale the update history V in order to make it
    compatible in scale with lr * grad.
    """
    logger.info('Scaling update history by %.6f (new lr / old lr)', correction)
    for p_key in param_keys:
        try:
            optimizer.state[p_key]['momentum_buffer'] *= correction
        except:
            continue


def _get_lr_change_ratio(cur_lr, new_lr):
    eps = 1e-10
    ratio = np.max(
        (new_lr / np.max((cur_lr, eps)), cur_lr / np.max((new_lr, eps)))
    )
    return ratio


def affine_grid_gen(rois, input_size, grid_size):
    rois = rois.detach()
    x1 = rois[:, 1::4] / 16.0
    y1 = rois[:, 2::4] / 16.0
    x2 = rois[:, 3::4] / 16.0
    y2 = rois[:, 4::4] / 16.0

    height = input_size[0]
    width = input_size[1]

    zero = Variable(rois.data.new(rois.size(0), 1).zero_())
    theta = torch.cat([ \
        (x2 - x1) / (width - 1),
        zero,
        (x1 + x2 - width + 1) / (width - 1),
        zero,
        (y2 - y1) / (height - 1),
        (y1 + y2 - height + 1) / (height - 1)], 1).view(-1, 2, 3)

    grid = F.affine_grid(theta, torch.Size((rois.size(0), 1, grid_size, grid_size)))

    return grid


def load_ckpt(model, ckpt):
    """Load checkpoint"""
    mapping, _ = model.detectron_weight_mapping
    state_dict = {}

    for name in ckpt:
        if mapping[name]:
            state_dict[name] = ckpt[name]

    model.load_state_dict(state_dict, strict=False)


def get_group_gn(dim):
    """
    get number of groups used by GroupNorm, based on number of channels
    """
    dim_per_gp = cfg.GROUP_NORM.DIM_PER_GP
    num_groups = cfg.GROUP_NORM.NUM_GROUPS

    assert dim_per_gp == -1 or num_groups == -1, \
        "GroupNorm: can only specify G or C/G."

    if dim_per_gp > 0:
        assert dim % dim_per_gp == 0
        group_gn = dim // dim_per_gp
    else:
        assert dim % num_groups == 0
        group_gn = num_groups
    return group_gn
