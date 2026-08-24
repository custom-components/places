# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/places/\_\_init\_\_.py      |      176 |        8 |       42 |        4 |     94% |207-208, 217-218, 257-259, 285-287, 342-\>354, 357-\>365, 368-\>370, 373-\>385 |
| custom\_components/places/advanced\_options.py |      258 |        8 |      148 |       21 |     93% |91-\>exit, 145-\>147, 214-\>202, 269-\>273, 274-\>276, 291, 292-\>300, 298-\>300, 304-\>exit, 316-\>324, 334-\>333, 336-\>333, 347-\>exit, 374, 402-\>404, 405-406, 430, 431-\>423, 434-435, 442, 447-\>449 |
| custom\_components/places/attributes.py        |       65 |        5 |       26 |        2 |     92% |65-\>exit, 126-127, 145, 150-151 |
| custom\_components/places/basic\_options.py    |       93 |        3 |       38 |        2 |     96% |304-305, 334 |
| custom\_components/places/button.py            |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/config\_flow.py      |      194 |        8 |      100 |        6 |     95% |87-\>83, 204-214, 229-239, 347, 352-\>354, 356-\>358 |
| custom\_components/places/config\_schema.py    |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/const.py             |      105 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/coordinator.py       |      334 |       14 |       96 |       16 |     93% |213, 337-338, 359-\>362, 512, 566-\>565, 568-\>570, 577, 579-\>589, 599, 609, 612, 632, 644, 677, 739-\>743, 784-786, 788-\>exit |
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
| custom\_components/places/update\_sensor.py    |      492 |       23 |      196 |       31 |     92% |166, 212-\>214, 214-\>exit, 293, 362-363, 368, 372, 376, 440-\>448, 510-\>exit, 511-\>513, 513-\>exit, 606-\>608, 614-\>617, 624, 734, 735-\>737, 739-743, 846-\>848, 848-\>850, 858, 888-\>exit, 896, 917-\>exit, 937-\>exit, 1013, 1017-\>1028, 1028-\>1039, 1039-\>exit, 1118, 1215, 1216-\>1226, 1218-1224, 1228-1230, 1235-\>exit |
| **TOTAL**                                      | **2434** |   **79** |  **814** |   **95** | **95%** |           |


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