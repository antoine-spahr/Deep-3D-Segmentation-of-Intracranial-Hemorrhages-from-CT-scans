"""
author: Antoine Spahr

date : 28.09.2020

----------

TO DO :
"""
import torch
import torch.nn as nn
import numpy as np

class BinaryDiceLoss(nn.Module):
    """
    Pytorch Module defining the Dice Loss for the Binary Segmentation Case.
    """
    def __init__(self, reduction='mean', p=2, alpha=1.0, eps=1):
        """
        Build a Binary Dice Loss Module.
        ----------
        INPUT
            |---- reduction (str) the reduction to apply over the batch. Default is 'mean'. Other options are: 'none' and 'sum'
            |---- p (uint) the power at which to elevate element before the denominator sum. Since the network output a
            |           sigmoid as prediction, a higher power will enforce the network to increase the prediction for
            |           positive pixels.
            |---- alpha (float) the weight of prediction for ground truth without positive (Prediction's loss reduced if alpha < 1.0)
            |---- eps (float) epsilon for numerical stability of division.
        OUTPUT
            |---- BinaryDiceLoss (nn.Module) the Loss module.
        """
        super(BinaryDiceLoss, self).__init__()
        assert reduction in ['mean', 'none', 'sum'], f"Reduction mode: '{reduction}' is not supported. Use either 'mean', 'sum' or 'none'."
        self.reduction = reduction
        self.p = p
        self.alpha = alpha
        self.eps = eps # for stability when mask and predictions are empty

    def forward(self, pred, mask):
        """
        Forward pass of the Binary Dice Loss defined as the 1-DiceCoeff.
        ----------
        INPUT
            |---- pred (torch.tensor) the binary prediction with dimension (Batch x Output Dimension).
            |---- mask (torch.tensor) the binary ground truth with dimension (Batch x Output Dimension).
        OUTPUT
            |---- DL (torch.tensor) the Dice Loss with the selected reduction over the Batch.
        """
        assert pred.shape == mask.shape, f'Prediction and Mask should have the same dimensions! Given: Prediction {pred.shape} / Mask {mask.shape}'
        sum_dim = tuple(range(1, pred.ndim)) # dimension of over which to sum : skip the batch dimension
        #compute the Dice Loss
        inter = torch.sum(pred * mask, dim=sum_dim)
        union = torch.sum(pred.pow(self.p), dim=sum_dim) + torch.sum(mask.pow(self.p), dim=sum_dim)
        DL = 1 - (2 * inter + self.eps)/(union + self.eps)
        # scale the loss with alpha
        DL = torch.where(mask.sum(dim=sum_dim) > 0, DL, self.alpha * DL)
        # Apply the reduction
        if self.reduction == 'mean':
            return DL.mean()
        elif self.reduction == 'sum':
            return DL.sum()
        elif self.reduction == 'none':
            return DL

class TverskyLoss(nn.Module):
    """
    Define the Tversky loss as a pytorch nn.Module.add_module
    """
    def __init__(self, alpha=1.0, beta=0.5, gamma=0.5, reduction='mean'):
        """
        Build a Binary Dice Loss Module.
        ----------
        INPUT
            |---- reduction (str) the reduction to apply over the batch. Default is 'mean'. Other options are: 'none' and 'sum'
            |---- alpha (float) the weight of prediction for ground truth without positive (Prediction's loss reduced if alpha < 1.0)
            |---- beta (float) the weight given to False negatives.
            |---- gamma (float) the weight given to False Positives.
        OUTPUT
            |---- TverskyLoss (nn.Module) the Loss module.
        """
        super(TverskyLoss, self).__init__()
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.reduction = reduction
        self.eps = 1

    def forward(self, pred, mask):
        """
        Forward pass of the Tverzsky Loss defined as the 1-TverskyCoeff.
        ----------
        INPUT
            |---- pred (torch.tensor) the binary prediction with dimension (Batch x Output Dimension).
            |---- mask (torch.tensor) the binary ground truth with dimension (Batch x Output Dimension).
        OUTPUT
            |---- TL (torch.tensor) the Tvresky Loss with the selected reduction over the Batch.
        """
        assert pred.shape == mask.shape, f'Prediction and Mask should have the same dimensions! Given: Prediction {pred.shape} / Mask {mask.shape}'
        sum_dim = tuple(range(1, pred.ndim)) # dimension of over which to sum : skip the batch dimension
        # compute TP, FP, FN
        TP = torch.sum(pred * mask, dim=sum_dim)
        FP = torch.sum(pred * (1 - mask), dim=sum_dim)
        FN = torch.sum((1 - pred) * mask, dim=sum_dim)
        # compute TF_loss
        TL = 1 - (TP + self.eps) / (TP + self.beta * FN + self.gamma * FP + self.eps)
        # scale loss of samples without positives on mask
        TL = torch.where(mask.sum(dim=sum_dim) > 0, TL, self.alpha * TL)
        # Apply the reduction
        if self.reduction == 'mean':
            return TL.mean()
        elif self.reduction == 'sum':
            return TL.sum()
        elif self.reduction == 'none':
            return TL

class ComboLoss(nn.Module):
    """
    Define the ComboLoss described by Asgari et al. It combines a Dice loss and a Binary cross entropy (BCE) loss in which
    the False Posistive (FP) and False Negative (FN) can be weighted.
    """
    def __init__(self, alpha=0.5, beta=0.5, reduction='mean', p=1):
        """
        Build a ComboLoss module for Binary segmentation.
        ----------
        INPUT
            |---- alpha (float) the relative importance of the BCE compared to the Dice loss. Must be between 0 and 1.
            |---- beta (float) the relative importance of FP compared to FN in the BCE Loss. Must be between 0 and 1.
            |---- reduction (str) the reduction to apply over batches. Supported: 'mean', 'sum', 'none'
            |---- p (int) the power at which to elevate element before the denominator sum. Since the network output a
            |           sigmoid as prediction, a higher power will enforce the network to increase the prediction for
            |           positive pixels.
        OUTPUT
            |---- ComboLoss (nn.Module) a combo loss module.
        """
        super(ComboLoss, self).__init__()
        assert alpha >= 0 and alpha <= 1, f'ValueError. alpha must in the range [0,1]. {alpha} given'
        assert beta >= 0 and beta <= 1, f'ValueError. beta must in the range [0,1]. {beta} given'
        self.alpha = alpha
        self.beta = beta
        self.reduction = reduction
        self.bin_dice_loss_fn = BinaryDiceLoss(reduction='none', p=p)

    def forward(self, pred, mask):
        """
        Forward pass of the ComboLoss.
        ----------
        INPUT
            |---- pred (torch.tensor) the binary prediction with dimension (Batch x Output Dimension).
            |---- mask (torch.tensor) the binary ground truth with dimension (Batch x Output Dimension).
        OUTPUT
            |---- combo_loss (torch.tensor) the ComboLoss with the selected reduction over the Batch.
        """
        assert pred.shape == mask.shape, f'Prediction and Mask should have the same dimensions! Given: Prediction {pred.shape} / Mask {mask.shape}'
        sum_dim = tuple(range(1, pred.ndim))

        dice_loss = self.bin_dice_loss_fn(pred, mask)
        bce_loss = - torch.sum(self.beta * mask * torch.log(pred + 1e-14) + (1 - self.beta) * (1 - mask) * torch.log(1 - pred + 1e-14), dim=sum_dim)
        combo_loss = self.alpha * bce_loss + (1 - self.alpha) * dice_loss

        # Apply the reduction
        if self.reduction == 'mean':
            return combo_loss.mean()
        elif self.reduction == 'sum':
            return combo_loss.sum()
        elif self.reduction == 'none':
            return combo_loss

class InfoNCELoss(nn.Module):
    """
    Define a Pytorch Module for the InfoNCELoss.
    """
    def __init__(self, set_size=None, tau=0.5, device='cuda'):
        """
        Build an InfoNCE loss module.
        ----------
        INPUT
            |---- set_size (int) the number of samples in the comparison set.
            |---- tau (float) the temprature hyperparameter.
            |---- device (str) the device to use.
        OUTPUT
            |---- InfoNCELoss (nn.Module) the contrastive loss module.
        """
        assert set_size is not None, 'The set size is a mandatory parameter'
        super(InfoNCELoss, self).__init__()
        self.tau = tau
        self.device = device
        self.set_size = set_size
        self.neg_mask = self.get_neg_mask(set_size)
        self.criterion = nn.CrossEntropyLoss(reduction="sum")
        self.similarity_f = nn.CosineSimilarity(dim=2)

    def get_neg_mask(self, set_size):
        """
        Make a boolean mask of negative samples on the similarity matrix. negatives are all except main diagonal, and
        lower and upper diagonal.
        ----------
        INPUT
            |---- set_size (int) the number of samples in the comparison set.
        OUTPUT
            |---- neg_mask (torch.boolTensor) the mask of negative.
        """
        # negative sample of similarity matrix are all except those in diagonal and upper/lower diagonal
        mask = torch.diag(torch.ones(2*set_size, device=self.device), diagonal=0)
        mask = mask + torch.diag(torch.ones(set_size, device=self.device), diagonal=set_size)
        mask = mask + torch.diag(torch.ones(set_size, device=self.device), diagonal=-set_size)
        return ~mask.bool()

    def forward(self, z1, z2):
        """
        Forward pass of the contrastive loss.
        ----------
        INPUT
            |---- z1 (torch.tensor) representation of the first representations (set_size x embed).
            |---- z2 (torch.tensor) representation of the second representations (set_size x embed).
        OUTPUT
            |---- loss (torch.tensor) the InfoNCE loss.
        """
        # concat both representation (2*Set_size x Embed)
        p = torch.cat((z1, z2), dim=0)
        # get similarity
        sim = self.similarity_f(p.unsqueeze(0), p.unsqueeze(1)) / self.tau
        # get positive and negative samples
        pos_sample = torch.cat((torch.diag(sim, self.set_size), torch.diag(sim, -self.set_size)), dim=0).reshape(2*self.set_size, 1)
        neg_sample = sim[self.neg_mask].reshape(2*self.set_size, -1)
        # make the logit and labels (= zero --> first element in logit to maximize)
        logits = torch.cat((pos_sample, neg_sample), dim=1)
        labels = torch.zeros(2 * self.set_size).to(self.device).long()
        # compute loss
        loss = self.criterion(logits, labels)
        return loss / (2 * self.set_size)

class LocalInfoNCELoss(nn.Module):
    """
    Define the extension of the InfoNCELoss for local structure as proposed in Chaitanya (2020). It enforces feature map
    region of two representation to be mapped similarly in a decoonvolutional network. Region are selected randomly on
    the feature map.
    """
    def __init__(self, tau=0.5, K=3, n_region=13, device='cuda'):
        """
        Build a Local InfoNCE loss module.
        ----------
        INPUT
            |---- tau (float) temperature hyperparameter of InfoNCE loss.
            |---- K (int) the size of the region to consider (region will be KxK).
            |---- n_region (int) the number of region to consider within a feature map.
            |---- device (str) the device to use
        OUTPUT
            |---- LocalInfoNCELoss (nn.Module) the local InfoNCE Loss.
        """
        super(LocalInfoNCELoss, self).__init__()
        self.tau = tau
        self.K = K
        self.n_region = n_region
        self.device = device

        self.pos_mask, self.neg_mask = self.get_masks(n_region)
        self.similarity_f = nn.CosineSimilarity(dim=3)
        self.criterion = nn.CrossEntropyLoss(reduction='mean')

    def get_masks(self, set_size):
        """
        Make a boolean mask of negative and positive samples on the similarity matrix. negatives are all except main diagonal, and
        lower and upper diagonal.
        ----------
        INPUT
            |---- set_size (int) the number of samples in the comparison set.
        OUTPUT
            |---- pos_mask (torch.boolTensor) the mask of positives.
            |---- neg_mask (torch.boolTensor) the mask of negative.
        """
        pos_mask = torch.diag(torch.ones(set_size, device=self.device), diagonal=set_size)
        pos_mask = pos_mask + torch.diag(torch.ones(set_size, device=self.device), diagonal=-set_size)
        neg_mask = pos_mask + torch.diag(torch.ones(2*set_size, device=self.device), diagonal=0)
        neg_mask = ~neg_mask.bool()
        pos_mask = pos_mask.bool()

        return pos_mask, neg_mask

    def get_sample_region_mask(self, feature_shape):
        """
        Generate a mask of the size of the feature map (HxW) for each element in the batch. A region mask for a batch
        element is a set of n_region non-overlapping squares of dimension KxK labeled by an ID between 1 and n_region.
        Therefore each square has a different value on the mask.
        ---------
        INPUT
            |---- feature_shape (tuple :(B, H, W, C)) the feature map dimension.
        OUTPUT
            |---- out (torch.tensor) the region mask with dimension B x H x W.
        """
        bs, H, W, C = feature_shape
        # generate indices in a reduced size (K time smaller) for each batch element (no replacement within batch element)
        idx_col = np.random.choice((H//self.K) * (W//self.K), self.n_region, replace=False)
        idx = np.random.rand(bs, (H//self.K) * (W//self.K)).argsort(axis=1)[:,idx_col]
        # define label of each region
        val = torch.arange(1, self.n_region + 1, device=self.device).repeat(bs, 1)
        mask = torch.zeros(bs, (H//self.K) * (W//self.K), device=self.device)
        mask[torch.tensor(np.repeat(np.arange(0, bs), self.n_region), device=self.device), torch.tensor(idx.ravel(), device=self.device)] = val.view(-1).float()
        # reshape
        mask = mask.view(bs, (H//self.K), (W//self.K))
        # upsample to get KxK region
        mask = torch.nn.functional.interpolate(mask.unsqueeze(0).unsqueeze(1).float(), scale_factor=(1,self.K,self.K), mode='nearest')[0,0,:,:]
        # pad to output size
        out = torch.zeros(feature_shape[:-1], device=self.device)
        out[:,:mask.shape[1],:mask.shape[2]] = mask

        return out

    def forward(self, f1, f2):
        """
        Forward pass of the LocalInfoNCE loss.
        ----------
        INPUT
            |---- f1 (torch.tensor) the first representation feature map as B x H x W x C.
            |---- f2 (torch.tensor) the second representation feature map as B x H x W x C.
        OUTPUT
            |---- loss (torch.tensor) the local InfoNCELoss.
        """
        bs = f1.shape[0]
        # get a mask of region to extract for each sample of batch : region mask -> B x H x W
        region_mask = self.get_sample_region_mask(f1.shape)
        # get indices of region positions for feature map indexation
        #indices = torch.cat([np.argwhere(region_mask==i) for i in range(1, self.n_region + 1)], dim=1)
        indices = torch.cat([torch.nonzero(region_mask==i) for i in range(1, self.n_region + 1)], dim=0)
        # extract region of feature map. fir : B x A x K*K*C
        f1r = f1[indices[:,0], indices[:,1], indices[:,2], :].view(self.n_region, bs, -1).permute(1,0,2)
        f2r = f2[indices[:,0], indices[:,1], indices[:,2], :].view(self.n_region, bs, -1).permute(1,0,2)
        # concat features map --> B x 2A x K*K*C
        p = torch.cat((f1r, f2r), dim=1)
        # compute cosine Similarity between KKC features --> sim : B x 2A x 2A
        sim = self.similarity_f(p.unsqueeze(1), p.unsqueeze(2)) / self.tau
        # get positive and negative samples from the similarity matrix
        pos_sample = sim[self.pos_mask.repeat(bs, 1, 1)].view(bs, 2*self.n_region, -1)
        neg_sample = sim[self.neg_mask.repeat(bs, 1, 1)].view(bs, 2*self.n_region, -1)
        # concat to get logit and un-ravel the batch dimension
        logits = torch.cat((pos_sample, neg_sample), dim=2).view(-1, 2*self.n_region-1)
        # make labels for CE : positive on position 0 --> labels = 0
        labels = torch.zeros(logits.shape[0], dtype=torch.long, device=self.device)
        # compute the CE entropy loss
        loss = nn.CrossEntropyLoss(reduction='mean')(logits, labels)

        return loss

class DiscountedL1(nn.Module):
    """
    Pytorch implementation of the Discounted L1 Loss proposed in Yu et al. 2018 (Generative Inpainting with Contextual
    Attention). It weight a L1 loss on a mask by the distance to the closest element not of the mask.
    """
    def __init__(self, gamma=0.99, reduction='mean', device='cuda'):
        """
        Build a DiscountedL1 Loss module.
        ----------
        INPUT
            |---- gamma (float) hyperparameter for the weight computation. The weight of a position is given by gamma ** dist.
            |---- reduction (str) the reduction to apply. One of 'mean', 'sum', 'none'.
            |---- device (str) the device on which to operate.
        OUTPUT
            |---- DiscountedL1 (nn.Module) the discounted L1 loss module.
        """
        super(DiscountedL1, self).__init__()
        self.gamma = torch.tensor(gamma, device=device)
        self.L1 = nn.L1Loss(reduction='none')
        assert reduction in ['mean', 'none', 'sum'], f"Reduction mode: '{reduction}' is not supported. Use either 'mean', 'sum' or 'none'."
        self.reduction = reduction
        self.device = device

    def forward(self, rec, im, mask):
        """
        Forward pass of the L1 Discounted loss. Note that a weight of 1.0 is used outside the mask (i.e. where mask = 0).
        ----------
        INPUT
            |---- rec (torch.tensor) the reconstructed image as (B x C x H x W).
            |---- im (torch.tensor) the reference image as (B x C x H x W).
            |---- mask (torch.tensor) the mask where to L1 is weighted as (B x 1 x H x W).
        """
        #assert rec.shape == im.shape, f'Shape mismatch between image and reconstruction: {rec.shape} vs {im.shape}'
        l1_loss = self.L1(rec, im)
        weight = (self.gamma.view(1,1,1,1) ** self.get_dist_mask(mask)) * mask # consider only pixel on mask and give more inportance of one close to border
        l1_loss = l1_loss * weight
        # Apply the reduction
        if self.reduction == 'mean':
            return l1_loss.mean()
        elif self.reduction == 'sum':
            return l1_loss.sum()
        elif self.reduction == 'none':
            return l1_loss

    def get_dist_mask(self, mask):
        """
        Compute the distance map of the given mask. Each pixel of the mask is assigned the minimum euclidian distance to
        a pixel with value 0.
        ----------
        INPUT
            |---- mask (torch.tensor) the mask where to L1 is weighted as (B x 1 x H x W).
        OUTPUT
            |---- dist_mask (torch.tensor) Same size tensor as mask with value of distance to closest 0 element.
        """
        # get mask of object contours (= dilation of mask - mask)
        border = nn.functional.max_pool2d(mask, 3, stride=1, padding=1, dilation=1) - mask
        dist_mask = []
        for i in range(mask.shape[0]):
            # compute distance between mask element and every non-mask border element
            dst = torch.cdist(torch.nonzero(mask[i,0,:,:]).unsqueeze(0).float(), torch.nonzero(border[i,0,:,:]).unsqueeze(0).float(), p=2)
            #dst = torch.cdist(torch.nonzero(mask[i,0,:,:]).unsqueeze(0).float(), torch.nonzero((1-mask[i,0,:,:])).unsqueeze(0).float(), p=2)
            # fill every mask position with the minimum distance (euclidian)
            msk = torch.zeros(mask.shape[2:], device=self.device)
            msk[torch.split(torch.nonzero(mask[i,0,:,:]).t(), 1, dim=0)] = dst.min(dim=2)[0]
            dist_mask.append(msk.view(1,1,*msk.shape))

        return torch.cat(dist_mask, dim=0)

class GDL(nn.Module):
    """

    """
    def __init__(self, reduction='mean', channels=1, device='cuda'):
        """

        """
        super(GDL, self).__init__()
        assert reduction in ['none', 'mean', 'sum'], f"Reduction startegy not supported. Must be one of ['none', 'mean', 'sum']. Given {reduction}."
        self.reduction = reduction

        self.w_h = torch.tensor([[[[0,  0, 0],
                                   [-1, 1, 0],
                                   [0,  0, 0]]]], device=device).float().repeat(1,channels,1,1)

        self.w_v = torch.tensor([[[[0, -1, 0],
                                   [0,  1, 0],
                                   [0,  0, 0]]]], device=device).float().repeat(1,channels,1,1)

    def forward(self, im, rec):
        """

        """
        im_gradH = torch.abs(nn.functional.conv2d(im, self.w_h, padding=1))
        im_gradV = torch.abs(nn.functional.conv2d(im, self.w_v, padding=1))
        rec_gradH = torch.abs(nn.functional.conv2d(rec, self.w_h, padding=1))
        rec_gradV = torch.abs(nn.functional.conv2d(rec, self.w_v, padding=1))

        loss = torch.abs(im_gradH - rec_gradH) + torch.abs(im_gradV - rec_gradV)
        loss = loss.sum(dim=[1,2,3])

        if self.reduction == 'none':
            return loss
        elif self.reduction == 'mean':
            return loss.mean()
        elif self.reduction == 'sum':
            return loss.sum()

class HSCLoss(nn.Module):
    """  """
    def __init__(self, reduction='mean'):
        """  """
        super().__init__()
        assert reduction in ['none', 'mean'], f"Reduction mode not supported. Must be either 'none' or 'mean'. Given '{reduction}'."
        self.reduction = reduction

    def forward(self, x, y):
        """
        y = label ; y=0 -> normal ; y=1 -> anomaly
        """
        # Pseudo Hubert loss
        Ax = torch.sqrt(x**2 + 1) - 1
        Ax = Ax.reshape(x.shape[0], -1).mean(-1) # mean over output feature map (batch wise)
        loss = torch.where(y == 1, -torch.log(1 - torch.exp(-Ax) + 1e-31), Ax)

        if self.reduction == 'none':
            return loss
        elif self.reduction == 'mean':
            return loss.mean()
