# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/places/\_\_init\_\_.py      |      171 |        8 |       40 |        4 |     94% |205-206, 215-216, 252-254, 280-282, 337-\>349, 352-\>360, 363-\>365, 368-\>380 |
| custom\_components/places/advanced\_options.py |      258 |        8 |      148 |       21 |     93% |91-\>exit, 145-\>147, 214-\>202, 269-\>273, 274-\>276, 291, 292-\>300, 298-\>300, 304-\>exit, 316-\>324, 334-\>333, 336-\>333, 347-\>exit, 374, 402-\>404, 405-406, 430, 431-\>423, 434-435, 442, 447-\>449 |
| custom\_components/places/attributes.py        |       65 |        5 |       26 |        2 |     92% |65-\>exit, 126-127, 145, 150-151 |
| custom\_components/places/basic\_options.py    |       87 |        4 |       38 |        6 |     92% |172, 247-\>exit, 272-\>285, 280-281, 287-\>exit, 310 |
| custom\_components/places/button.py            |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/config\_flow.py      |      194 |        8 |      100 |        6 |     95% |87-\>83, 204-214, 229-239, 347, 352-\>354, 356-\>358 |
| custom\_components/places/config\_schema.py    |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/const.py             |      105 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/coordinator.py       |      329 |       18 |       96 |       15 |     91% |213, 339-340, 361-\>364, 514, 568-\>567, 570-\>572, 579, 581-\>591, 601, 611, 614, 634, 646, 679, 741-\>745, 783-792 |
| custom\_components/places/entity.py            |       38 |        2 |        2 |        1 |     92% |   88, 130 |
| custom\_components/places/helpers.py           |       16 |        0 |        2 |        0 |    100% |           |
| custom\_components/places/location.py          |       29 |        1 |       10 |        1 |     95% |        71 |
| custom\_components/places/migration.py         |       86 |        2 |       16 |        0 |     98% |   207-208 |
| custom\_components/places/osm\_client.py       |       78 |        2 |       16 |        2 |     96% |  155, 226 |
| custom\_components/places/parse\_osm.py        |      155 |        3 |       88 |        9 |     95% |76, 100-\>exit, 111, 140-\>exit, 162-\>167, 185, 297-\>302, 337-\>342, 342-\>348 |
| custom\_components/places/persistence.py       |       52 |        0 |        8 |        0 |    100% |           |
| custom\_components/places/select.py            |       24 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/sensor.py            |       69 |        0 |       10 |        0 |    100% |           |
| custom\_components/places/switch.py            |       24 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/text.py              |       24 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/tracker.py           |       86 |        0 |       16 |        0 |    100% |           |
| custom\_components/places/update\_sensor.py    |      488 |       23 |      196 |       31 |     92% |164, 210-\>212, 212-\>exit, 291, 351-352, 357, 361, 365, 429-\>437, 499-\>exit, 500-\>502, 502-\>exit, 595-\>597, 603-\>606, 613, 723, 724-\>726, 728-732, 835-\>837, 837-\>839, 847, 877-\>exit, 885, 906-\>exit, 926-\>exit, 1002, 1006-\>1017, 1017-\>1028, 1028-\>exit, 1107, 1204, 1205-\>1215, 1207-1213, 1217-1219, 1224-\>exit |
| **TOTAL**                                      | **2414** |   **84** |  **812** |   **98** | **94%** |           |


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