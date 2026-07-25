# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/places/\_\_init\_\_.py      |       16 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/advanced\_options.py |      256 |        8 |      148 |       21 |     93% |83-\>exit, 129-\>131, 189-\>177, 245-\>249, 250-\>252, 267, 268-\>276, 274-\>276, 280-\>exit, 292-\>300, 309-\>308, 311-\>308, 321-\>exit, 346, 372-\>374, 375-376, 400, 401-\>393, 404-405, 412, 417-\>419 |
| custom\_components/places/attributes.py        |       65 |        0 |       26 |        1 |     99% | 49-\>exit |
| custom\_components/places/basic\_options.py    |       93 |        4 |       44 |        7 |     92% |151-\>143, 168, 238-\>exit, 261-\>274, 269-270, 276-\>exit, 299 |
| custom\_components/places/config\_flow.py      |      184 |        8 |       96 |        6 |     95% |80-\>79, 192-202, 217-227, 326, 331-\>333, 335-\>337 |
| custom\_components/places/config\_schema.py    |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/const.py             |      113 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/helpers.py           |       73 |        6 |        6 |        0 |     92% |27-28, 143-152 |
| custom\_components/places/location.py          |       45 |        4 |       16 |        4 |     87% |55, 62, 69, 86 |
| custom\_components/places/osm\_client.py       |       78 |        2 |       16 |        2 |     96% |  122, 193 |
| custom\_components/places/parse\_osm.py        |      160 |        8 |       90 |       12 |     91% |68, 72-75, 86, 109-\>exit, 119, 147-\>exit, 168-\>173, 190, 290-\>295, 297-\>302, 302-\>307, 317-\>exit, 335-\>340, 340-\>346 |
| custom\_components/places/pipeline.py          |       36 |        2 |        6 |        1 |     93% |     60-66 |
| custom\_components/places/sensor.py            |      268 |       18 |       82 |       16 |     89% |138-\>140, 140-\>144, 144-\>150, 226-\>228, 229, 255, 293, 306, 328-\>333, 335, 443-\>442, 448-\>447, 464, 591-600, 615-632, 670-\>674, 716-\>718, 735-\>exit |
| custom\_components/places/tracker.py           |       82 |        0 |       16 |        0 |    100% |           |
| custom\_components/places/update\_sensor.py    |      408 |       20 |      164 |       36 |     90% |153-\>155, 168, 177-178, 198-\>200, 200-\>202, 202-\>205, 206-\>205, 209-\>215, 215-\>220, 217-\>216, 245-246, 251, 255, 259, 316-\>324, 347, 354-\>367, 384-\>exit, 385-\>387, 387-\>exit, 475-\>477, 481-\>484, 491, 662-\>664, 664-\>666, 699-\>exit, 707, 728-\>exit, 746-\>exit, 812, 816-\>824, 824-\>832, 832-\>exit, 920, 1010, 1011-\>1021, 1013-1019, 1023-1025, 1030-\>exit |
| **TOTAL**                                      | **1895** |   **80** |  **710** |  **106** | **93%** |           |


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