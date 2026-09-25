from surprise import SVD, Dataset, Reader
from surprise.model_selection import cross_validate


def evaluate_svd_movielens()
    file_path =r"D:\4sf23ci052\ml-latest-small\ratings.csv"
    reader = Reader(
        line_format="user item rating timestamp",
        sep=",",
        rating_scale=(0.5, 5.0),
        skip_lines=1,
    ) 
    print("Loading MovieLens dataset...")
    data = Dataset.load_from_file(file_path, reader=reader) 
    algo = SVD(random_state=42)
    print("Evaluating SVD performance using 5-fold cross-validation...")
    cv_results = cross_validate(
        algo, data, measures=["RMSE", "MAE"], cv=3, verbose=True
    )

    mean_rmse = cv_results["test_rmse"].mean()
    print(f"\nMean RMSE across 5 folds: {mean_rmse:.4f}")


if __name__ == "__main__":
    evaluate_svd_movielens()
