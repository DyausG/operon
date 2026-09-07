# Third-Party Notices

This repository includes or depends on third-party materials. Their original
licenses and attribution remain in effect.

## AI4I 2020 Predictive Maintenance Dataset

The file `data/ai4i2020.csv` contains the synthetic **AI4I 2020 Predictive
Maintenance Dataset** from the UCI Machine Learning Repository.

- Citation: *AI4I 2020 Predictive Maintenance Dataset* [Dataset]. (2020). UCI
  Machine Learning Repository.
- DOI: https://doi.org/10.24432/C5HS5C
- License: Creative Commons Attribution 4.0 International (CC BY 4.0),
  https://creativecommons.org/licenses/by/4.0/

The dataset is used for model training and evaluation. Feature normalization and
derived features are implemented in `core/dataset.py`; the source CSV is retained
as distributed.

## Software dependencies

Python and JavaScript dependencies retain their own licenses. Exact dependency
versions and source metadata are recorded in `uv.lock` and
`frontend/package-lock.json`. The committed frontend bundle preserves embedded
license and copyright notices, including the React MIT license notices.
