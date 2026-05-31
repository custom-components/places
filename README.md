# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/places/\_\_init\_\_.py      |       21 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/advanced\_options.py |      256 |        8 |      148 |       21 |     93% |83-\>exit, 129-\>131, 189-\>177, 245-\>249, 250-\>252, 267, 268-\>276, 274-\>276, 280-\>exit, 292-\>300, 309-\>308, 311-\>308, 321-\>exit, 346, 372-\>374, 375-376, 400, 401-\>393, 404-405, 412, 417-\>419 |
| custom\_components/places/attributes.py        |       65 |        0 |       26 |        1 |     99% | 53-\>exit |
| custom\_components/places/basic\_options.py    |       93 |        4 |       44 |        7 |     92% |151-\>143, 168, 238-\>exit, 261-\>274, 269-270, 276-\>exit, 299 |
| custom\_components/places/config\_flow.py      |      184 |        8 |       96 |        6 |     95% |80-\>79, 192-202, 217-227, 326, 331-\>333, 335-\>337 |
| custom\_components/places/config\_schema.py    |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/const.py             |      111 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/helpers.py           |       16 |        0 |        2 |        0 |    100% |           |
| custom\_components/places/location.py          |       45 |        4 |       16 |        4 |     87% |55, 62, 69, 86 |
| custom\_components/places/osm\_client.py       |       78 |        2 |       16 |        2 |     96% |  122, 193 |
| custom\_components/places/parse\_osm.py        |      152 |        8 |       88 |       15 |     90% |69, 73-76, 87, 110-\>exit, 127, 155-\>exit, 176-\>181, 198, 293-\>298, 300-\>305, 305-\>310, 320-\>exit, 338-\>343, 343-\>349, 362-\>366, 363-\>362, 366-\>exit |
| custom\_components/places/persistence.py       |       88 |        6 |       12 |        0 |     94% |152, 192-200, 223-224 |
| custom\_components/places/pipeline.py          |       36 |        2 |        6 |        1 |     93% |     60-64 |
| custom\_components/places/sensor.py            |      264 |       18 |       82 |       16 |     88% |133-\>135, 135-\>139, 139-\>145, 224-\>226, 227, 253, 281, 294, 316-\>321, 323, 424-\>423, 429-\>428, 448, 575-584, 599-616, 654-\>658, 700-\>702, 719-\>exit |
| custom\_components/places/tracker.py           |       82 |        0 |       16 |        0 |    100% |           |
| custom\_components/places/update\_sensor.py    |      399 |       20 |      156 |       34 |     90% |151-\>153, 166, 175-176, 190-\>192, 192-\>194, 194-\>197, 198-\>197, 201-\>207, 207-\>212, 209-\>208, 237-238, 243, 247, 251, 308-\>316, 339, 346-\>359, 376-\>exit, 377-\>379, 379-\>exit, 467-\>469, 473-\>476, 483, 673-\>exit, 681, 702-\>exit, 720-\>exit, 786, 790-\>798, 798-\>806, 806-\>exit, 894, 984, 985-\>995, 987-993, 997-999, 1004-\>exit |
| **TOTAL**                                      | **1908** |   **80** |  **708** |  **107** | **93%** |           |


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