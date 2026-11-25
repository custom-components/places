# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/places/\_\_init\_\_.py      |      161 |        8 |       40 |        4 |     94% |176-177, 186-187, 226-228, 254-256, 311-\>323, 326-\>334, 337-\>339, 342-\>354 |
| custom\_components/places/advanced\_options.py |       75 |        0 |       34 |        1 |     99% | 111-\>113 |
| custom\_components/places/attributes.py        |       65 |        5 |       26 |        2 |     92% |65-\>exit, 126-127, 150-151, 212 |
| custom\_components/places/basic\_options.py    |       93 |        3 |       38 |        2 |     96% |304-305, 334 |
| custom\_components/places/button.py            |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/config\_flow.py      |       95 |        0 |       46 |        1 |     99% |   87-\>83 |
| custom\_components/places/config\_schema.py    |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/const.py             |      110 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/coordinator.py       |      300 |       17 |       84 |       13 |     92% |223, 329-335, 437-438, 459-\>462, 477, 542-\>544, 552, 554-\>564, 585, 588, 608, 620, 652 |
| custom\_components/places/display\_options.py  |      150 |        0 |       46 |        1 |     99% | 217-\>219 |
| custom\_components/places/entity.py            |       38 |        2 |        2 |        1 |     92% |   88, 130 |
| custom\_components/places/helpers.py           |       16 |        0 |        2 |        0 |    100% |           |
| custom\_components/places/location.py          |       29 |        1 |       10 |        1 |     95% |        71 |
| custom\_components/places/migration.py         |       86 |        2 |       16 |        0 |     98% |   207-208 |
| custom\_components/places/osm\_client.py       |       78 |        2 |       16 |        2 |     96% |  155, 226 |
| custom\_components/places/parse\_osm.py        |      155 |        2 |       88 |        5 |     97% |75, 99-\>exit, 161-\>166, 184, 296-\>301 |
| custom\_components/places/persistence.py       |       52 |        0 |        8 |        0 |    100% |           |
| custom\_components/places/select.py            |       24 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/sensor.py            |       69 |        0 |       10 |        0 |    100% |           |
| custom\_components/places/state.py             |      111 |        4 |       26 |        3 |     95% |231, 332-334, 336-\>exit |
| custom\_components/places/switch.py            |       24 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/text.py              |       24 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/tracker.py           |       98 |        0 |       20 |        0 |    100% |           |
| custom\_components/places/update\_sensor.py    |      526 |       17 |      206 |       19 |     95% |202, 349, 491, 560, 583-\>exit, 584-\>586, 586-\>exit, 680-\>682, 686-\>689, 806, 807-\>809, 811-815, 932, 955-\>exit, 975-\>exit, 1090-\>1101, 1189, 1284, 1285-\>1295, 1287-1293, 1297-1299, 1304-\>exit |
| **TOTAL**                                      | **2415** |   **63** |  **718** |   **55** | **96%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/custom-components/places/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/custom-components/places/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fcustom-components%2Fplaces%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.