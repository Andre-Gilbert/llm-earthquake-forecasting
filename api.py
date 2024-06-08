"""API calls."""

import os
from datetime import datetime, timedelta
from urllib import parse

import catboost as cb
import pandas as pd
import requests
import streamlit as st


@st.cache_data
def get_recent_earthquakes(
    start_time: datetime = (datetime.now() - timedelta(days=30)).date(),
    end_time: datetime = datetime.now().date(),
    limit: int = 20000,
    min_depth: int = -100,
    max_depth: int = 1000,
    min_magnitude: int | None = None,
    max_magnitude: int | None = None,
    alert_level: str | None = None,
) -> pd.DataFrame:
    params = {
        "format": "csv",
        "starttime": start_time,
        "endtime": end_time,
        "limit": limit,
        "mindepth": min_depth,
        "maxdepth": max_depth,
        "eventtype": "earthquake",
    }
    if min_magnitude is not None:
        params["minmagnitude"] = min_magnitude
    if max_magnitude is not None:
        params["maxmagnitude"] = max_magnitude
    if alert_level is not None:
        params["alertlevel"] = alert_level
    url = "https://earthquake.usgs.gov/fdsnws/event/1/query?" + parse.urlencode(params)
    return pd.read_csv(url)


@st.cache_data
def count_earthquakes(
    start_time: datetime = (datetime.now() - timedelta(days=30)).date(),
    end_time: datetime = datetime.now().date(),
    limit: int = 20000,
    min_depth: int = -100,
    max_depth: int = 1000,
    min_magnitude: int | None = None,
    max_magnitude: int | None = None,
    alert_level: str | None = None,
) -> int:
    params = {
        "format": "geojson",
        "starttime": start_time,
        "endtime": end_time,
        "limit": limit,
        "mindepth": min_depth,
        "maxdepth": max_depth,
        "minmagnitude": min_magnitude,
        "maxmagnitude": max_magnitude,
        "alertlevel": alert_level,
        "eventtype": "earthquake",
    }
    return requests.get(
        "https://earthquake.usgs.gov/fdsnws/event/1/count",
        params=params,
        timeout=None,
    ).json()


_START_LAG = 3
_END_LAG = 10


def get_regions() -> list[str]:
    df = get_recent_earthquakes()
    df["region"] = df.place.str.split(", ", expand=True)[1]
    df.region = df.region.fillna(df.place)
    df.region = df.region.replace({"CA": "California", "B.C.": "Baja California"})
    return set(
        [
            "California",
            "Alaska",
            "Nevada",
            "Hawaii",
            "Washington",
            "Utah",
            "Montana",
            "Puerto Rico",
            "Indonesia",
            "Chile",
            "Baja California",
            "Oklahoma",
            "Japan",
            "Greece",
            "Papua New Guinea",
            "Philippines",
            "Mexico",
            "Italy",
            "Russia",
            "Idaho",
            "Aleutian Islands",
            "Tonga",
            "Oregon",
            "Wyoming",
            "Turkey",
        ]
    ) & set(df.region.unique())


@st.cache_resource
def load_model() -> cb.CatBoostRegressor:
    path = os.path.join(os.path.dirname(__file__), "./ml/multi_output_model")
    model = cb.CatBoostRegressor(cat_features=["region"])
    return model.load_model(path)


def reindex(group, delta):
    start_date = group.index.min()
    end_date = pd.Timestamp((datetime.now() + timedelta(days=delta)).date())
    date_range = pd.date_range(start=start_date, end=end_date, freq="d")
    return group.reindex(date_range).ffill()


def preprocess_data(df: pd.DataFrame, region: str | None = None) -> pd.DataFrame:
    df = df.copy()

    df["region"] = df.place.str.split(", ", expand=True)[1]
    df.region = df.region.fillna(df.place)
    df.region = df.region.replace({"CA": "California", "B.C.": "Baja California"})

    df.time = pd.to_datetime(df.time)
    df.time = df.time.dt.tz_localize(None)
    df = df.sort_values("time")
    df = df.set_index("time")

    df = df[["depth", "mag", "region", "latitude", "longitude"]]

    df = df.groupby("region").resample("d").mean().reset_index()
    df = df.set_index("time")

    if region is None:
        regions = get_regions()
        df = df.loc[df.region.isin(regions)]

        df = (
            df.groupby("region")[["region", "mag", "depth", "latitude", "longitude"]]
            .apply(lambda group: reindex(group, 0), include_groups=False)
            .reset_index(0, drop=True)
        )
    else:
        df = df.loc[df.region == region]

        start_date = df.index.min()
        end_date = pd.Timestamp(datetime.today().date())
        date_range = pd.date_range(start=start_date, end=end_date, freq="d")
        df = df.reindex(date_range)

        df = df.ffill()

    return df


def create_features(df: pd.DataFrame, region: str | None) -> pd.DataFrame:
    df = df.copy()

    if region is None:
        regions = get_regions()
        df = df.loc[df.region.isin(regions)]

        df = (
            df.groupby("region")[["region", "mag", "depth", "latitude", "longitude"]]
            .apply(lambda group: reindex(group, 3), include_groups=False)
            .reset_index(0, drop=True)
        )
    else:
        start_date = df.index.min()
        end_date = pd.Timestamp((datetime.now() + timedelta(days=3)).date())
        date_range = pd.date_range(start=start_date, end=end_date, freq="d")
        df = df.reindex(date_range)

        df.region = df.region.ffill()

    df["day"] = df.index.day
    df["dayofweek"] = df.index.dayofweek
    df["dayofyear"] = df.index.dayofyear

    for i in range(_START_LAG, _END_LAG + 1):
        df[f"mag_lag_{i}"] = df.groupby("region").mag.shift(i)

    for i in range(_START_LAG, _END_LAG + 1):
        df[f"depth_lag_{i}"] = df.groupby("region").depth.shift(i)

    df[f"mag_rolling_mean_{_START_LAG}"] = df.groupby("region").mag.transform(
        lambda x: x.rolling(window=_START_LAG).mean()
    )
    df[f"mag_rolling_std_{_START_LAG}"] = df.groupby("region").mag.transform(
        lambda x: x.rolling(window=_START_LAG).std()
    )
    df[f"depth_rolling_mean_{_START_LAG}"] = df.groupby("region").depth.transform(
        lambda x: x.rolling(window=_START_LAG).mean()
    )
    df[f"depth_rolling_std_{_START_LAG}"] = df.groupby("region").depth.transform(
        lambda x: x.rolling(window=_START_LAG).std()
    )

    df[f"mag_rolling_mean_{_END_LAG}"] = df.groupby("region").mag.transform(lambda x: x.rolling(window=_END_LAG).mean())
    df[f"mag_rolling_std_{_END_LAG}"] = df.groupby("region").mag.transform(lambda x: x.rolling(window=_END_LAG).std())
    df[f"depth_rolling_mean_{_END_LAG}"] = df.groupby("region").depth.transform(
        lambda x: x.rolling(window=_END_LAG).mean()
    )
    df[f"depth_rolling_std_{_END_LAG}"] = df.groupby("region").depth.transform(
        lambda x: x.rolling(window=_END_LAG).std()
    )

    return df


def get_forecast(region: str | None = None) -> pd.DataFrame:
    model = load_model()
    df = get_recent_earthquakes()
    df = preprocess_data(df, region)
    df = create_features(df, region)
    features = (
        [
            "day",
            "dayofweek",
            "dayofyear",
            f"mag_rolling_mean_{_START_LAG}",
            f"mag_rolling_std_{_START_LAG}",
            f"depth_rolling_mean_{_START_LAG}",
            f"depth_rolling_std_{_START_LAG}",
            f"mag_rolling_mean_{_END_LAG}",
            f"mag_rolling_std_{_END_LAG}",
            f"depth_rolling_mean_{_END_LAG}",
            f"depth_rolling_std_{_END_LAG}",
        ]
        + [f"mag_lag_{i}" for i in range(_START_LAG, _END_LAG + 1)]
        + [f"depth_lag_{i}" for i in range(_START_LAG, _END_LAG + 1)]
    )
    cat_features = ["region"]
    forecast = model.predict(df[features + cat_features])
    df_forecast = pd.DataFrame(forecast, columns=["Magnitude Forecast", "Depth Forecast"])
    df = df.reset_index()
    df = df.join(df_forecast)
    df = df[["index", "mag", "Magnitude Forecast", "depth", "Depth Forecast", "region", "latitude", "longitude"]]
    df = df.rename(
        columns={
            "index": "Date",
            "mag": "Magnitude",
            "depth": "Depth",
            "region": "Region",
            "latitude": "Latitude",
            "longitude": "Longitude",
        }
    )
    date = pd.Timestamp.now().normalize() - pd.Timedelta(days=7)
    return df.loc[df.Date >= date]


def forecast_earthquakes() -> pd.DataFrame:
    df = get_forecast()
    today = pd.Timestamp.now().normalize()
    df = df.loc[df.Date >= today]
    return df
