# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/places/\_\_init\_\_.py      |       16 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/advanced\_options.py |      256 |        8 |      152 |       22 |     93% |121-\>123, 181-\>169, 237-\>241, 242-\>244, 259, 260-\>268, 266-\>268, 270-\>272, 275-\>exit, 287-\>295, 297-\>exit, 307-\>306, 309-\>306, 319-\>exit, 344, 370-\>372, 373-374, 398, 399-\>391, 402-403, 410, 415-\>417 |
| custom\_components/places/basic\_options.py    |       93 |        4 |       44 |        7 |     92% |140-\>132, 157, 227-\>exit, 250-\>263, 258-259, 265-\>exit, 288 |
| custom\_components/places/config\_flow.py      |      188 |        8 |       96 |        6 |     95% |78-\>77, 190-200, 215-225, 324, 329-\>331, 333-\>335 |
| custom\_components/places/const.py             |      113 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/helpers.py           |       73 |        6 |        6 |        0 |     92% |27-28, 143-152 |
| custom\_components/places/parse\_osm.py        |      145 |        3 |       86 |       20 |     90% |76, 99-\>exit, 116, 144-\>exit, 165-\>170, 187, 282-\>287, 287-\>294, 289-\>294, 294-\>299, 299-\>304, 304-\>309, 309-\>exit, 321-\>327, 327-\>332, 332-\>338, 338-\>exit, 351-\>355, 352-\>351, 355-\>exit |
| custom\_components/places/sensor.py            |      280 |       19 |      106 |       19 |     89% |140-\>142, 142-\>146, 146-\>152, 227-\>229, 230, 256, 294, 307, 329-\>333, 335, 409-\>exit, 428-\>427, 433-\>432, 450, 559, 586-\>exit, 607-616, 631-648, 685-\>689, 731-\>733, 750-\>exit |
| custom\_components/places/update\_sensor.py    |      448 |       25 |      174 |       36 |     90% |148-152, 167-\>169, 182, 191-192, 212-\>214, 214-\>216, 216-\>219, 220-\>219, 223-\>229, 229-\>234, 231-\>230, 259-260, 265, 269, 273, 330-\>338, 361, 368-\>381, 393-\>395, 395-\>exit, 485-\>487, 487-\>490, 497, 693-\>exit, 701, 731-\>exit, 749-\>exit, 836, 900, 904-\>911, 911-\>918, 918-\>exit, 1003, 1093, 1094-\>1104, 1096-1102, 1106-1108, 1113-\>exit, 1193-1194 |
| **TOTAL**                                      | **1612** |   **73** |  **664** |  **110** | **92%** |           |


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