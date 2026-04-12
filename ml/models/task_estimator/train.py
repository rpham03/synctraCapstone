# Trains a gradient-boosted model to predict how long a task will take in minutes.
"""
Task Duration Estimator
-----------------------
Predicts estimated completion time (in minutes) for a task given:
  - task type (homework, reading, project, exam prep)
  - course subject
  - historical completion times for similar tasks

Model: Gradient Boosted Regressor (scikit-learn)
"""
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
import joblib


def train(data_path: str, model_out: str = "task_estimator.joblib") -> None:
    df = pd.read_csv(data_path)

    features = ["task_type_encoded", "course_encoded", "word_count", "days_until_due"]
    target = "actual_minutes"

    X_train, X_test, y_train, y_test = train_test_split(
        df[features], df[target], test_size=0.2, random_state=42
    )

    model = GradientBoostingRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    mae = mean_absolute_error(y_test, model.predict(X_test))
    print(f"MAE: {mae:.1f} minutes")

    joblib.dump(model, model_out)
    print(f"Model saved to {model_out}")


if __name__ == "__main__":
    train("../../data/processed/task_history.csv")
