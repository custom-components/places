# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/custom-components/places/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                           |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| custom\_components/places/\_\_init\_\_.py      |      161 |        6 |       40 |        4 |     95% |190-191, 221-223, 249-251, 296-\>308, 311-\>319, 322-\>324, 327-\>339 |
| custom\_components/places/advanced\_options.py |      258 |        8 |      148 |       21 |     93% |87-\>exit, 133-\>135, 202-\>190, 256-\>260, 261-\>263, 278, 279-\>287, 285-\>287, 291-\>exit, 303-\>311, 320-\>319, 322-\>319, 332-\>exit, 357, 383-\>385, 386-387, 411, 412-\>404, 415-416, 423, 428-\>430 |
| custom\_components/places/attributes.py        |       65 |        5 |       26 |        2 |     92% |52-\>exit, 104-105, 120, 125-126 |
| custom\_components/places/basic\_options.py    |       87 |        4 |       38 |        6 |     92% |162, 232-\>exit, 255-\>268, 263-264, 270-\>exit, 291 |
| custom\_components/places/button.py            |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/config\_flow.py      |      193 |        8 |      100 |        6 |     95% |84-\>80, 201-211, 226-236, 335, 340-\>342, 344-\>346 |
| custom\_components/places/config\_schema.py    |       18 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/const.py             |      105 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/coordinator.py       |      329 |       18 |       96 |       15 |     91% |203, 321-322, 343-\>346, 473, 527-\>526, 529-\>531, 538, 540-\>550, 555, 564, 567, 586, 598, 623, 684-\>688, 726-735 |
| custom\_components/places/entity.py            |       38 |        2 |        2 |        1 |     92% |   85, 120 |
| custom\_components/places/helpers.py           |       16 |        0 |        2 |        0 |    100% |           |
| custom\_components/places/location.py          |       29 |        1 |       10 |        1 |     95% |        63 |
| custom\_components/places/migration.py         |       86 |        2 |       16 |        0 |     98% |   195-196 |
| custom\_components/places/osm\_client.py       |       78 |        2 |       16 |        2 |     96% |  123, 194 |
| custom\_components/places/parse\_osm.py        |      155 |        3 |       88 |        9 |     95% |75, 98-\>exit, 108, 136-\>exit, 157-\>162, 179, 288-\>293, 327-\>332, 332-\>338 |
| custom\_components/places/persistence.py       |       52 |        0 |        8 |        0 |    100% |           |
| custom\_components/places/select.py            |       24 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/sensor.py            |       69 |        0 |       10 |        0 |    100% |           |
| custom\_components/places/switch.py            |       24 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/text.py              |       24 |        0 |        0 |        0 |    100% |           |
| custom\_components/places/tracker.py           |       82 |        0 |       16 |        0 |    100% |           |
| custom\_components/places/update\_sensor.py    |      484 |       23 |      196 |       31 |     92% |152, 198-\>200, 200-\>exit, 274, 332-333, 338, 342, 346, 409-\>417, 481-\>exit, 482-\>484, 484-\>exit, 578-\>580, 586-\>589, 596, 705, 706-\>708, 710-714, 811-\>813, 813-\>815, 823, 852-\>exit, 860, 881-\>exit, 901-\>exit, 973, 977-\>988, 988-\>999, 999-\>exit, 1077, 1170, 1171-\>1181, 1173-1179, 1183-1185, 1190-\>exit |
| **TOTAL**                                      | **2395** |   **82** |  **812** |   **98** | **94%** |           |


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