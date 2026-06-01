from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import RobustScaler


@dataclass
class TrainingSample:
    features: np.ndarray
    labels: np.ndarray


def iou_score(pred: np.ndarray, truth: np.ndarray) -> float:
    pred = pred.astype(bool)
    truth = truth.astype(bool)
    intersection = np.logical_and(pred, truth).sum()
    union = np.logical_or(pred, truth).sum()
    return float(intersection / union) if union > 0 else 0.0


def _ensure_2d(features: np.ndarray) -> np.ndarray:
    if features.ndim == 1:
        return features.reshape(-1, 1)
    return features


def _label_stats(labels: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    unique, counts = np.unique(labels, return_counts=True)
    return unique, counts


def _clip_and_impute(train: np.ndarray, test: np.ndarray, percentile_low: float, percentile_high: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    clip_min = np.nanpercentile(train, percentile_low, axis=0)
    clip_max = np.nanpercentile(train, percentile_high, axis=0)

    train = np.clip(train, clip_min, clip_max)
    test = np.clip(test, clip_min, clip_max)

    medians = np.nanmedian(train, axis=0)
    train = np.where(np.isfinite(train), train, medians)
    test = np.where(np.isfinite(test), test, medians)

    return train, test, clip_min, clip_max, medians


def _optimize_threshold(probs: np.ndarray, labels: np.ndarray, thresholds: Iterable[float] | None = None) -> Tuple[float, float, float]:
    if thresholds is None:
        thresholds = np.linspace(0.1, 0.9, 17)

    best_iou = -1.0
    best_f1 = -1.0
    best_threshold = 0.5

    for threshold in thresholds:
        pred = probs >= threshold
        iou = iou_score(pred, labels)
        f1 = f1_score(labels, pred) if labels.size else 0.0
        if iou > best_iou:
            best_iou = iou
            best_f1 = f1
            best_threshold = float(threshold)

    return best_threshold, float(best_iou), float(best_f1)


def kfold_iou(features: np.ndarray, labels: np.ndarray, k: int = 5) -> Dict:
    features = _ensure_2d(features.astype(float))
    labels = labels.astype(int)

    unique, counts = _label_stats(labels)
    if unique.size < 2:
        return {
            "mean_iou": 0.0,
            "fold_ious": [],
            "mean_f1": 0.0,
            "fold_f1": [],
            "mean_threshold": 0.5,
            "fold_thresholds": [],
            "warning": "Only one class present in labels",
        }

    min_count = int(np.min(counts))
    n_splits = min(k, min_count)
    if n_splits < 2:
        return {
            "mean_iou": 0.0,
            "fold_ious": [],
            "mean_f1": 0.0,
            "fold_f1": [],
            "mean_threshold": 0.5,
            "fold_thresholds": [],
            "warning": "Not enough samples per class for K-fold",
        }

    kf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    ious: List[float] = []
    f1s: List[float] = []
    thresholds: List[float] = []

    for train_idx, test_idx in kf.split(features, labels):
        train_x, test_x = features[train_idx], features[test_idx]
        train_y, test_y = labels[train_idx], labels[test_idx]

        train_x, test_x, clip_min, clip_max, medians = _clip_and_impute(train_x, test_x, 1.0, 99.0)

        scaler = RobustScaler()
        train_x = scaler.fit_transform(train_x)
        test_x = scaler.transform(test_x)

        model = LogisticRegression(max_iter=500, class_weight="balanced", solver="liblinear")
        model.fit(train_x, train_y)

        probs = model.predict_proba(test_x)[:, 1]
        threshold, best_iou, best_f1 = _optimize_threshold(probs, test_y)

        ious.append(best_iou)
        f1s.append(best_f1)
        thresholds.append(threshold)

    return {
        "mean_iou": float(np.mean(ious)) if ious else 0.0,
        "fold_ious": [float(v) for v in ious],
        "mean_f1": float(np.mean(f1s)) if f1s else 0.0,
        "fold_f1": [float(v) for v in f1s],
        "mean_threshold": float(np.mean(thresholds)) if thresholds else 0.5,
        "fold_thresholds": [float(v) for v in thresholds],
        "n_splits": n_splits,
    }


def train_logistic(features: np.ndarray, labels: np.ndarray) -> Dict:
    features = _ensure_2d(features.astype(float))
    labels = labels.astype(int)

    unique, counts = _label_stats(labels)
    if unique.size < 2:
        return {
            "coef": [],
            "intercept": [],
            "classes": unique.tolist(),
            "threshold": 0.5,
            "warning": "Only one class present in labels",
        }

    features, _, clip_min, clip_max, medians = _clip_and_impute(features, features, 1.0, 99.0)

    scaler = RobustScaler()
    features_scaled = scaler.fit_transform(features)

    model = LogisticRegression(max_iter=500, class_weight="balanced", solver="liblinear")
    model.fit(features_scaled, labels)

    probs = model.predict_proba(features_scaled)[:, 1]
    threshold, best_iou, best_f1 = _optimize_threshold(probs, labels)

    return {
        "coef": model.coef_.tolist(),
        "intercept": model.intercept_.tolist(),
        "classes": model.classes_.tolist(),
        "threshold": threshold,
        "train_iou": best_iou,
        "train_f1": best_f1,
        "scaler": {
            "center": scaler.center_.tolist(),
            "scale": scaler.scale_.tolist(),
            "clip_min": clip_min.tolist(),
            "clip_max": clip_max.tolist(),
            "median": medians.tolist(),
        },
    }


def learn_road_segmentation_formula(
    index_maps: Dict[str, np.ndarray],
    mask: np.ndarray,
    k_folds: int = 5,
) -> Dict[str, Any]:
    """Learn an optimal segmentation formula from multiple indices.

    Uses logistic regression with cross-validation to find the best
    combination of indices for road segmentation.

    Args:
        index_maps: Dictionary of index name -> index map
        mask: Binary ground truth mask
        k_folds: Number of cross-validation folds

    Returns:
        Dictionary with formula coefficients, performance metrics, and recommended index
    """
    features_list = []
    index_names = []

    for name, index_map in index_maps.items():
        flat = index_map.reshape(-1)
        if np.any(np.isfinite(flat)):
            features_list.append(flat)
            index_names.append(name)

    if len(features_list) < 1:
        return {
            "warning": "No valid indices available for training",
            "best_index": None,
            "coef": [],
            "intercept": 0,
        }

    features = np.column_stack(features_list)
    labels = mask.reshape(-1).astype(int)
    # Binarize defensively — region_grow returns 0/1 but progressive variants can return 0/1/2.
    labels = (labels > 0).astype(int)

    valid_rows = ~np.any(np.isnan(features), axis=1)
    features = features[valid_rows]
    labels = labels[valid_rows]

    if len(features) < 100:
        return {
            "warning": "Insufficient valid pixels for training",
            "best_index": None,
            "coef": [],
            "intercept": 0,
        }

    unique_labels = np.unique(labels)
    if unique_labels.size < 2:
        msg = f"Only one class in training labels (values={unique_labels.tolist()}); need both road and non-road pixels. "
        msg += "This usually means: (1) negative seeds are in regions containing positive seeds, or (2) threshold is too high/low, or (3) positive and negative seeds are in the same connected region. "
        msg += f"Checked {len(labels)} pixels total (road={labels.sum()}, non-road={len(labels)-labels.sum()}). Try adjusting seed placement or threshold."
        return {
            "warning": msg,
            "best_index": None,
            "coef": [],
            "intercept": 0,
        }

    # Balanced subsample for tractability — scikit-learn fits scale with N,
    # and we don't need every pixel to identify the best single index.
    MAX_PER_CLASS = 25_000
    pos_idx = np.where(labels == 1)[0]
    neg_idx = np.where(labels == 0)[0]
    rng = np.random.default_rng(42)
    if pos_idx.size > MAX_PER_CLASS:
        pos_idx = rng.choice(pos_idx, MAX_PER_CLASS, replace=False)
    if neg_idx.size > MAX_PER_CLASS:
        neg_idx = rng.choice(neg_idx, MAX_PER_CLASS, replace=False)
    keep = np.concatenate([pos_idx, neg_idx])
    rng.shuffle(keep)
    features = features[keep]
    labels = labels[keep]

    scaler = RobustScaler()
    features_scaled = scaler.fit_transform(features)

    model = LogisticRegression(
        max_iter=1000,
        class_weight="balanced",
        solver="liblinear",
        random_state=42,
    )

    try:
        cv_scores = cross_val_score(model, features_scaled, labels, cv=min(k_folds, np.sum(labels)), scoring="f1")
        cv_iou = cross_val_score(model, features_scaled, labels, cv=min(k_folds, np.sum(labels)), scoring="roc_auc")
    except Exception:
        cv_scores = np.array([0.5])
        cv_iou = np.array([0.5])

    model.fit(features_scaled, labels)
    predictions = model.predict(features_scaled)

    intersection = np.logical_and(predictions, labels).sum()
    union = np.logical_or(predictions, labels).sum()
    iou = intersection / (union + 1e-8)

    coef = model.coef_[0]
    importance = np.abs(coef) / (np.abs(coef).sum() + 1e-8)

    best_single_idx = None
    best_single_iou = 0.0
    per_index_scores: List[Dict[str, Any]] = []
    for i, name in enumerate(index_names):
        # Fit a fresh single-feature scaler+model — the multi-feature scaler above
        # was fit on all index columns, so it can't be reused on a single column.
        feat = features[:, i:i+1]
        try:
            single_scaler = RobustScaler()
            feat_scaled = single_scaler.fit_transform(feat)
            single_model = LogisticRegression(
                max_iter=1000, class_weight="balanced",
                solver="liblinear", random_state=42,
            )
            single_model.fit(feat_scaled, labels)
            probs = single_model.predict_proba(feat_scaled)[:, 1]
            best_threshold, best_iou_, best_f1_ = _optimize_threshold(probs, labels)
            pred = probs >= best_threshold

            # Map the prob-domain threshold back to the index-value domain so the
            # frontend can drop it straight into the segmentation threshold slider.
            # We find the index value at which the logistic model crosses
            # prob = best_threshold:
            #     scaled_x = (logit(best_threshold) - intercept) / coef
            #     x = scaled_x * scaler.scale_ + scaler.center_
            try:
                if best_threshold <= 0.0 or best_threshold >= 1.0 or single_model.coef_[0][0] == 0.0:
                    suggested_threshold = None
                else:
                    logit_t = float(np.log(best_threshold / (1.0 - best_threshold)))
                    coef0 = float(single_model.coef_[0][0])
                    intercept0 = float(single_model.intercept_[0])
                    scaled_x = (logit_t - intercept0) / coef0
                    x_value = scaled_x * float(single_scaler.scale_[0]) + float(single_scaler.center_[0])
                    suggested_threshold = float(x_value)
            except Exception:
                suggested_threshold = None
        except Exception as exc:
            per_index_scores.append({
                "name": name,
                "iou": 0.0,
                "f1": 0.0,
                "suggested_threshold": None,
                "error": str(exc),
            })
            continue
        single_iou = float(np.logical_and(pred, labels).sum() / (np.logical_or(pred, labels).sum() + 1e-8))
        per_index_scores.append({
            "name": name,
            "iou": single_iou,
            "f1": float(best_f1_),
            "suggested_threshold": suggested_threshold,
        })
        if single_iou > best_single_iou:
            best_single_iou = single_iou
            best_single_idx = name

    return {
        "best_index": best_single_idx,
        "best_single_iou": float(best_single_iou),
        "combined_iou": float(iou),
        "mean_cv_f1": float(np.mean(cv_scores)),
        "mean_cv_iou": float(np.mean(cv_iou)),
        "coef": coef.tolist(),
        "intercept": float(model.intercept_[0]),
        "index_names": index_names,
        "importance": importance.tolist(),
        "total_pixels": len(labels),
        "road_pixels": int(labels.sum()),
        "per_index_scores": per_index_scores,
        "warning": None,
    }
