# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/places/\_\_init\_\_.py      |       16 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/advanced\_options.py |      256 |        8 |      152 |       22 |     93% |126->128, 189->177, 245->249, 250->252, 267, 268->276, 274->276, 278->280, 283->exit, 295->303, 305->exit, 316->315, 318->315, 329->exit, 353, 383->385, 386-387, 411, 412->404, 415-416, 423, 428->430 |
| custom\_components/places/basic\_options.py    |       93 |        4 |       44 |        7 |     92% |119->111, 131, 186->exit, 203->216, 211-212, 218->exit, 235 |
| custom\_components/places/config\_flow.py      |      179 |       27 |       86 |        8 |     83% |70->69, 154, 164-176, 187-199, 206-210, 251-253, 274, 287-296 |
| custom\_components/places/const.py             |      113 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/helpers.py           |       52 |        4 |        2 |        0 |     93% |20-21, 87-88 |
| custom\_components/places/parse\_osm.py        |      142 |        3 |       86 |       20 |     90% |66, 85->exit, 98, 123->exit, 137->142, 155, 238->243, 243->250, 245->250, 250->255, 255->260, 260->265, 265->exit, 273->279, 279->284, 284->290, 290->exit, 303->307, 304->303, 307->exit |
| custom\_components/places/sensor.py            |      277 |       19 |      106 |       19 |     89% |133->135, 135->139, 139->145, 210->212, 213, 239, 277, 290, 313->317, 319, 385->exit, 400->399, 405->404, 418, 473, 485->exit, 497-506, 516-533, 563->567, 609->611, 628->exit |
| custom\_components/places/update\_sensor.py    |      450 |       30 |      170 |       34 |     90% |136-140, 149->151, 164, 173-174, 190->192, 192->194, 194->197, 198->197, 201->207, 207->212, 209->208, 233-234, 240, 244, 248, 300->308, 326, 333->346, 358->360, 360->exit, 446->448, 448->453, 460, 629->exit, 637, 667->exit, 685->exit, 766, 824, 828->835, 835->842, 842->exit, 922, 998-1004, 1008-1018, 1023->exit, 1088-1089 |
| **TOTAL**                                      | **1578** |   **95** |  **646** |  **110** | **90%** |           |


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