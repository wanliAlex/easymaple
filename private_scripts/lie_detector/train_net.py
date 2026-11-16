"""Train the Lie Detector shape net on the recorded corpus.

Data: .npz per clip from build_dataset.py (2-channel frames + green-cursor
labels in NET coords). Samples are 8-frame stacks ending at a labeled frame.
Hard-variant clips (2026-07-11_*) are oversampled — they are the reason this
model exists. Validation is two held-out clips (one easy, one hard) never
seen in training; the metric that matters is % of frames localized within
60/80 interior px (the game's tolerance), especially on the hard clip.

Usage:
    python private_scripts/lie_detector/train_net.py
"""
import os
import sys

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.easymaple.detection import lie_detector_net as N  # noqa: E402

DATA_DIR = os.path.join("training_data", "lie_detector", "dataset")
VAL_CLIPS = {"2026-07-09_15-09-28.npz", "2026-07-11_01-16-11.npz"}
HARD_PREFIX = "2026-07-11"          # human-played hard-variant recordings
HARD_OVERSAMPLE = 4.0
EPOCHS = 30
BATCH = 32
LR = 1e-3
HIST = (N.N_FRAMES - 1) * N.FRAME_STEP    # stack history in stored frames


class ClipDataset(Dataset):
    def __init__(self, files, train=True):
        self.train = train
        self.clips = []
        self.index = []          # (clip_idx, frame_idx_in_store)
        self.weights = []
        for ci, path in enumerate(files):
            z = np.load(path)
            chans, labels = z["chans"], z["labels"]
            self.clips.append((chans, labels))
            hard = os.path.basename(path).startswith(HARD_PREFIX)
            for j in range(HIST, len(chans)):
                if np.isfinite(labels[j][0]):
                    self.index.append((ci, j))
                    self.weights.append(HARD_OVERSAMPLE if hard else 1.0)

    def __len__(self):
        return len(self.index)

    def __getitem__(self, i):
        ci, j = self.index[i]
        chans, labels = self.clips[ci]
        stack = [chans[j - HIST + k * N.FRAME_STEP] for k in range(N.N_FRAMES)]
        x = N.stack_to_tensor(stack)
        gx, gy = labels[j]
        if self.train and np.random.rand() < 0.5:      # horizontal flip
            x = x[:, :, ::-1].copy()
            gx = N.NET_W - 1 - gx
        hm = N.gt_to_heatmap((gx, gy))
        return torch.from_numpy(x), torch.from_numpy(hm)[None], torch.tensor([gx, gy])


def focal_loss(logits, target):
    """CenterNet penalty-reduced focal loss on a Gaussian heatmap target."""
    p = torch.sigmoid(logits)
    pos = target.ge(0.999).float()
    neg_w = (1 - target).pow(4)
    pos_loss = -((1 - p).pow(2) * torch.log(p.clamp(min=1e-6)) * pos)
    neg_loss = -(neg_w * p.pow(2) * torch.log((1 - p).clamp(min=1e-6)) * (1 - pos))
    npos = pos.sum().clamp(min=1)
    return (pos_loss.sum() + neg_loss.sum()) / npos


@torch.no_grad()
def validate(model, ds, device, interior_scale=1.94):
    """Localization: heatmap argmax vs GT, reported in interior px."""
    model.eval()
    errs = []
    for i in range(0, len(ds), 2):
        x, _, gt = ds[i]
        hm = torch.sigmoid(model(x[None].to(device)))[0, 0].cpu().numpy()
        iy, ix = np.unravel_index(np.argmax(hm), hm.shape)
        px, py = (ix + 0.5) * N.STRIDE, (iy + 0.5) * N.STRIDE
        errs.append(float(np.hypot(px - gt[0], py - gt[1])) * interior_scale)
    errs = np.array(errs)
    return dict(n=len(errs), med=float(np.median(errs)),
                w60=float(np.mean(errs < 60)), w80=float(np.mean(errs < 80)))


def main():
    files = sorted(os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
                   if f.endswith(".npz"))
    train_files = [f for f in files if os.path.basename(f) not in VAL_CLIPS]
    val_easy = [f for f in files if os.path.basename(f) in VAL_CLIPS
                and not os.path.basename(f).startswith(HARD_PREFIX)]
    val_hard = [f for f in files if os.path.basename(f) in VAL_CLIPS
                and os.path.basename(f).startswith(HARD_PREFIX)]
    print(f"train clips: {len(train_files)}, val: {[os.path.basename(f) for f in val_easy + val_hard]}")

    tr = ClipDataset(train_files, train=True)
    ve = ClipDataset(val_easy, train=False)
    vh = ClipDataset(val_hard, train=False)
    print(f"train samples: {len(tr)}  val-easy: {len(ve)}  val-hard: {len(vh)}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = N.build_model().to(device)
    n_par = sum(p.numel() for p in model.parameters())
    print(f"device={device} params={n_par/1e3:.0f}k")

    sampler = WeightedRandomSampler(tr.weights, num_samples=len(tr), replacement=True)
    dl = DataLoader(tr, batch_size=BATCH, sampler=sampler, num_workers=0,
                    pin_memory=(device == "cuda"))
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS * len(dl))

    best = -1.0
    out = str(N.DEFAULT_WEIGHTS)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    for ep in range(EPOCHS):
        model.train()
        tot = 0.0
        for x, hm, _ in dl:
            x, hm = x.to(device), hm.to(device)
            loss = focal_loss(model(x), hm)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot += float(loss)
        me = validate(model, ve, device)
        mh = validate(model, vh, device)
        score = mh["w80"] + 0.2 * me["w80"]
        mark = ""
        if score > best:
            best = score
            torch.save(model.state_dict(), out)
            mark = "  * saved"
        print(f"ep{ep:02d} loss={tot/len(dl):.3f}  "
              f"val-easy med={me['med']:5.1f}px w80={100*me['w80']:3.0f}%  "
              f"VAL-HARD med={mh['med']:5.1f}px w60={100*mh['w60']:3.0f}% "
              f"w80={100*mh['w80']:3.0f}%{mark}")
    print(f"best score={best:.3f} -> {out}")


if __name__ == "__main__":
    main()
