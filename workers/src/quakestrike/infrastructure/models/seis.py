"""Verified SEIS 1.0.1 inference routes."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path

from quakestrike.domain.features import FEATURE_NAMES, INPUT_SCHEMA_VERSION, create_feature_snapshot
from quakestrike.domain.prediction import ROUTE_NAMES, InvalidPredictionOutput
from quakestrike.infrastructure.models.release_manifest import (
    SELECTED_RELEASE_MANIFEST_URI,
    ManifestValidationError,
    load_verified_release_manifest,
)

OUTPUT_SCHEMA_VERSION = "quakestrike.prediction-output.v2"


class SeisModel:
    """Load the eight native models once and keep their manifest feature order."""

    def __init__(self, artifact_directory: Path, release_id: object) -> None:
        self.artifact_directory = artifact_directory
        self.release_id = release_id
        self.verify_artifacts()
        document = json.loads((artifact_directory / SELECTED_RELEASE_MANIFEST_URI).read_bytes())
        if (
            document["input_schema_version"] != INPUT_SCHEMA_VERSION
            or document["output_schema_version"] != OUTPUT_SCHEMA_VERSION
        ):
            raise ManifestValidationError("The SEIS input or output schema is unsupported.")

        from catboost import CatBoostRegressor
        from lightgbm import Booster

        self.routes = {}
        bundle = artifact_directory / "seis-1.0.1"
        for route in document["routes"].values():
            model_type = route["default_model"]
            if model_type not in {"lightgbm", "catboost"}:
                raise ManifestValidationError("The SEIS model type is unsupported.")
            for target in route["targets"]:
                name = target["name"]
                features = tuple(target["features"])
                if (
                    name in self.routes
                    or len(features) != 10
                    or set(features) != set(FEATURE_NAMES)
                ):
                    raise ManifestValidationError(
                        "The SEIS route or feature contract is unsupported."
                    )
                path = bundle / target["artifact_path"]
                if model_type == "lightgbm":
                    model = Booster(model_file=str(path))
                    count = model.num_feature()
                else:
                    model = CatBoostRegressor()
                    model.load_model(str(path))
                    count = len(model.feature_names_)
                if count != len(features):
                    raise ManifestValidationError("A SEIS model has the wrong feature count.")
                self.routes[name] = (model_type, model, features, target["kind"])
        if set(self.routes) != ROUTE_NAMES:
            raise ManifestValidationError("The SEIS route set is unsupported.")
        self.verify_artifacts()

    def verify_artifacts(self) -> None:
        release = load_verified_release_manifest(
            self.artifact_directory, SELECTED_RELEASE_MANIFEST_URI, require_selected_policy=True
        )
        if release.release_id != self.release_id:
            raise ManifestValidationError("The configured SEIS release ID is wrong.")

    def predict(self, features: Mapping[str, object]) -> Mapping[str, object]:
        values = create_feature_snapshot(features).values
        outputs = {}
        for name, (model_type, model, ordered_features, kind) in self.routes.items():
            row = [values[field] for field in ordered_features]
            if model_type == "lightgbm":
                import numpy as np

                result = model.predict(np.asarray([row], dtype=float), num_threads=1)[0]
            else:
                prediction_type = "Exponent" if kind == "poisson" else "RawFormulaVal"
                result = model.predict([row], prediction_type=prediction_type, thread_count=1)[0]
            outputs[name] = float(result)
            if not math.isfinite(outputs[name]):
                raise InvalidPredictionOutput("A SEIS route returned a non-finite value.")
        quantiles = sorted(outputs[name] for name in ("maximum_q05", "maximum_q50", "maximum_q95"))
        for name, value in zip(
            ("maximum_q05", "maximum_q50", "maximum_q95"), quantiles, strict=True
        ):
            outputs[name] = max(1.0, value)
        return outputs
