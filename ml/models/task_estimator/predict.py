# Loads the trained task duration model and exposes a predict() interface for the backend.
"""Load the trained estimator and predict task duration."""
import joblib
import numpy as np


class TaskDurationEstimator:
    def __init__(self, model_path: str = "task_estimator.joblib"):
        self.model = joblib.load(model_path)

    def predict(self, task_type: int, course: int, word_count: int, days_until_due: int) -> int:
        features = np.array([[task_type, course, word_count, days_until_due]])
        minutes = self.model.predict(features)[0]
        return max(15, int(minutes))  # floor at 15 min
