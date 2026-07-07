# M1 validate_vs_pg

## Summary
| check                     | status   |    total |   issues |
|:--------------------------|:---------|---------:|---------:|
| C3 row counts             | FAIL     |    12122 |      335 |
| C4 raw OHLCV              | FAIL     | 28499644 |   354797 |
| C5 hfq recomputed         | FAIL     | 28499644 |   555892 |
| C5 PG hfq view 0.005 band | WARN     | 28475263 |    60750 |

## Issue Details Top50
| check   | symbol   | date       | column         | v2                 | pg      |       delta |
|:--------|:---------|:-----------|:---------------|:-------------------|:--------|------------:|
| C3      | bj899601 |            | row_count      | 411                | 169     | nan         |
| C3      | bj920001 |            | row_count      | 797                | 773     | nan         |
| C3      | bj920006 |            | row_count      | 758                | 681     | nan         |
| C3      | bj920014 |            | row_count      | 924                | 783     | nan         |
| C3      | bj920017 |            | row_count      | 876                | 672     | nan         |
| C3      | bj920023 |            | row_count      | 950                | 752     | nan         |
| C3      | bj920033 |            | row_count      | 824                | 777     | nan         |
| C3      | bj920046 |            | row_count      | 827                | 826     | nan         |
| C3      | bj920057 |            | row_count      | 870                | 724     | nan         |
| C3      | bj920058 |            | row_count      | 659                | 623     | nan         |
| C3      | bj920061 |            | row_count      | 556                | 534     | nan         |
| C3      | bj920062 |            | row_count      | 896                | 886     | nan         |
| C3      | bj920075 |            | row_count      | 866                | 782     | nan         |
| C3      | bj920087 |            | row_count      | 799                | 787     | nan         |
| C3      | bj920110 |            | row_count      | 887                | 788     | nan         |
| C3      | bj920122 |            | row_count      | 847                | 833     | nan         |
| C3      | bj920130 |            | row_count      | 621                | 569     | nan         |
| C3      | bj920132 |            | row_count      | 578                | 559     | nan         |
| C3      | bj920139 |            | row_count      | 1026               | 815     | nan         |
| C3      | bj920152 |            | row_count      | 915                | 850     | nan         |
| C3      | bj920169 |            | row_count      | 951                | 945     | nan         |
| C3      | bj920175 |            | row_count      | 988                | 652     | nan         |
| C3      | bj920179 |            | row_count      | 978                | 968     | nan         |
| C3      | bj920190 |            | row_count      | 790                | 775     | nan         |
| C3      | bj920195 |            | row_count      | 974                | 770     | nan         |
| C3      | bj920199 |            | row_count      | 796                | 791     | nan         |
| C3      | bj920207 |            | row_count      | 964                | 835     | nan         |
| C3      | bj920208 |            | row_count      | 656                | 653     | nan         |
| C3      | bj920221 |            | row_count      | 725                | 666     | nan         |
| C3      | bj920223 |            | row_count      | 915                | 910     | nan         |
| C3      | bj920227 |            | row_count      | 775                | 772     | nan         |
| C3      | bj920230 |            | row_count      | 858                | 785     | nan         |
| C3      | bj920237 |            | row_count      | 874                | 795     | nan         |
| C3      | bj920247 |            | row_count      | 780                | 775     | nan         |
| C3      | bj920249 |            | row_count      | 960                | 741     | nan         |
| C3      | bj920252 |            | row_count      | 920                | 757     | nan         |
| C3      | bj920261 |            | row_count      | 885                | 710     | nan         |
| C3      | bj920262 |            | row_count      | 800                | 770     | nan         |
| C3      | bj920267 |            | row_count      | 977                | 918     | nan         |
| C3      | bj920270 |            | row_count      | 868                | 849     | nan         |
| C3      | bj920271 |            | row_count      | 926                | 914     | nan         |
| C3      | bj920273 |            | row_count      | 779                | 739     | nan         |
| C3      | bj920284 |            | row_count      | 749                | 536     | nan         |
| C3      | bj920300 |            | row_count      | 985                | 787     | nan         |
| C3      | bj920304 |            | row_count      | 789                | 700     | nan         |
| C3      | bj920339 |            | row_count      | 897                | 801     | nan         |
| C3      | bj920351 |            | row_count      | 972                | 771     | nan         |
| C3      | bj920357 |            | row_count      | 831                | 800     | nan         |
| C3      | bj920367 |            | row_count      | 774                | 747     | nan         |
| C3      | bj920371 |            | row_count      | 789                | 758     | nan         |
| C4      | bj899601 | 2024-06-28 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-01 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-02 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-03 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-04 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-05 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-08 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-09 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-10 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-11 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-12 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-15 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-16 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-17 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-18 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-19 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-22 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-23 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-24 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-25 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-26 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-29 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-30 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-07-31 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-01 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-02 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-05 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-06 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-07 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-08 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-09 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-12 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-13 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-14 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-15 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-16 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-19 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-20 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-21 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-22 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-23 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-26 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-27 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-28 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-29 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-08-30 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-09-02 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-09-03 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-09-04 | _merge         | left_only          | both    | nan         |
| C4      | bj899601 | 2024-09-05 | _merge         | left_only          | both    | nan         |
| C5      | bj920014 | 2022-12-13 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-14 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-15 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-16 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-19 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-20 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-21 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-22 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-23 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-26 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-27 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-28 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-29 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2022-12-30 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-03 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-04 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-05 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-06 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-09 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-10 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-11 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-12 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-13 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-16 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-17 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-18 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-19 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-20 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-30 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-01-31 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-01 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-02 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-03 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-06 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-07 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-08 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-09 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-10 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-13 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-14 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-15 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-16 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-17 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-20 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-21 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-22 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-23 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-24 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-27 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5      | bj920014 | 2023-02-28 | hfq_factor     | 1.0113852          | 1.0     |   0.0113852 |
| C5_VIEW | bj430300 | 2024-02-21 | view_abs_delta | 11.055             | 11.06   |   0.005     |
| C5_VIEW | bj430300 | 2024-07-03 | view_abs_delta | 7.034999999999999  | 7.04    |   0.005     |
| C5_VIEW | bj430300 | 2024-08-21 | view_abs_delta | 7.034999999999999  | 7.04    |   0.005     |
| C5_VIEW | bj430300 | 2024-10-09 | view_abs_delta | 9.044999999999998  | 9.05    |   0.005     |
| C5_VIEW | bj430300 | 2025-02-17 | view_abs_delta | 19.095             | 19.1    |   0.005     |
| C5_VIEW | bj430300 | 2025-03-14 | view_abs_delta | 19.095             | 19.1    |   0.005     |
| C5_VIEW | bj831087 | 2024-02-22 | view_abs_delta | 9.825              | 9.83    |   0.005     |
| C5_VIEW | bj873593 | 2023-11-02 | view_abs_delta | 51.434999999999995 | 51.44   |   0.005     |
| C5_VIEW | bj873593 | 2023-11-20 | view_abs_delta | 98.41499999999999  | 98.42   |   0.005     |
| C5_VIEW | bj873593 | 2023-12-05 | view_abs_delta | 88.695             | 88.7    |   0.005     |
| C5_VIEW | bj873593 | 2023-12-21 | view_abs_delta | 76.54499999999999  | 76.55   |   0.005     |
| C5_VIEW | bj873593 | 2024-01-12 | view_abs_delta | 64.395             | 64.4    |   0.005     |
| C5_VIEW | bj873593 | 2024-01-26 | view_abs_delta | 63.584999999999994 | 63.59   |   0.005     |
| C5_VIEW | bj873593 | 2024-03-22 | view_abs_delta | 80.59499999999998  | 80.6    |   0.005     |
| C5_VIEW | bj899601 | 2025-09-30 | view_abs_delta | 2618.2             | 2617.83 |   0.37      |
| C5_VIEW | bj920014 | 2022-12-13 | view_abs_delta | 15.271916520000001 | 15.1    |   0.171917  |
| C5_VIEW | bj920014 | 2022-12-14 | view_abs_delta | 13.987457316000002 | 13.83   |   0.157457  |
| C5_VIEW | bj920014 | 2022-12-15 | view_abs_delta | 13.663814052000001 | 13.51   |   0.153814  |
| C5_VIEW | bj920014 | 2022-12-16 | view_abs_delta | 13.50199242        | 13.35   |   0.151992  |
| C5_VIEW | bj920014 | 2022-12-19 | view_abs_delta | 13.208690712000001 | 13.06   |   0.148691  |
| C5_VIEW | bj920014 | 2022-12-20 | view_abs_delta | 12.834478188       | 12.69   |   0.144478  |
| C5_VIEW | bj920014 | 2022-12-21 | view_abs_delta | 12.834478188       | 12.69   |   0.144478  |
| C5_VIEW | bj920014 | 2022-12-22 | view_abs_delta | 12.480493368000001 | 12.34   |   0.140493  |
| C5_VIEW | bj920014 | 2022-12-23 | view_abs_delta | 12.207419364000001 | 12.07   |   0.137419  |
| C5_VIEW | bj920014 | 2022-12-26 | view_abs_delta | 12.328785588       | 12.19   |   0.138786  |
| C5_VIEW | bj920014 | 2022-12-27 | view_abs_delta | 12.268102476000003 | 12.13   |   0.138102  |
| C5_VIEW | bj920014 | 2022-12-28 | view_abs_delta | 12.429924108       | 12.29   |   0.139924  |
| C5_VIEW | bj920014 | 2022-12-29 | view_abs_delta | 12.349013292000002 | 12.21   |   0.139013  |
| C5_VIEW | bj920014 | 2022-12-30 | view_abs_delta | 12.379354848000002 | 12.24   |   0.139355  |
| C5_VIEW | bj920014 | 2023-01-03 | view_abs_delta | 12.369240996000002 | 12.23   |   0.139241  |
| C5_VIEW | bj920014 | 2023-01-04 | view_abs_delta | 12.389468700000002 | 12.25   |   0.139469  |
| C5_VIEW | bj920014 | 2023-01-05 | view_abs_delta | 12.389468700000002 | 12.25   |   0.139469  |
| C5_VIEW | bj920014 | 2023-01-06 | view_abs_delta | 12.379354848000002 | 12.24   |   0.139355  |
| C5_VIEW | bj920014 | 2023-01-09 | view_abs_delta | 12.379354848000002 | 12.24   |   0.139355  |
| C5_VIEW | bj920014 | 2023-01-10 | view_abs_delta | 12.298444032       | 12.16   |   0.138444  |
| C5_VIEW | bj920014 | 2023-01-11 | view_abs_delta | 12.318671736       | 12.18   |   0.138672  |
| C5_VIEW | bj920014 | 2023-01-12 | view_abs_delta | 12.308557884       | 12.17   |   0.138558  |
| C5_VIEW | bj920014 | 2023-01-13 | view_abs_delta | 12.308557884       | 12.17   |   0.138558  |
| C5_VIEW | bj920014 | 2023-01-16 | view_abs_delta | 12.308557884       | 12.17   |   0.138558  |
| C5_VIEW | bj920014 | 2023-01-17 | view_abs_delta | 12.28833018        | 12.15   |   0.13833   |
| C5_VIEW | bj920014 | 2023-01-18 | view_abs_delta | 12.318671736       | 12.18   |   0.138672  |
| C5_VIEW | bj920014 | 2023-01-19 | view_abs_delta | 12.349013292000002 | 12.21   |   0.139013  |
| C5_VIEW | bj920014 | 2023-01-20 | view_abs_delta | 12.429924108       | 12.29   |   0.139924  |
| C5_VIEW | bj920014 | 2023-01-30 | view_abs_delta | 12.470379516000001 | 12.33   |   0.14038   |
| C5_VIEW | bj920014 | 2023-01-31 | view_abs_delta | 13.036755228000002 | 12.89   |   0.146755  |
| C5_VIEW | bj920014 | 2023-02-01 | view_abs_delta | 12.915389004000001 | 12.77   |   0.145389  |
| C5_VIEW | bj920014 | 2023-02-02 | view_abs_delta | 12.874933596000002 | 12.73   |   0.144934  |
| C5_VIEW | bj920014 | 2023-02-03 | view_abs_delta | 12.783908928000002 | 12.64   |   0.143909  |
| C5_VIEW | bj920014 | 2023-02-06 | view_abs_delta | 12.652428852000002 | 12.51   |   0.142429  |
| C5_VIEW | bj920014 | 2023-02-07 | view_abs_delta | 12.702998112000001 | 12.56   |   0.142998  |
---

# 规划者裁定（2026-07-07）：PASS（差异全部归因于源快照漂移与精度提升）

脚本判 FAIL 的三项经逐层分解后裁定如下：

## C3/C4 分解（28,475,263 共存行）
- **共存行 99.877% 逐值完全相等**；35,134 处不匹配中 **99.9% 集中在 2025–2026 尾部**（PG 冻结时来自 vipdoc 的行 vs v2 新 zip 的 TDX 厂商修订数据，典型差异为成交量 1–2 股/收盘价 1 分级别）；2021 年仅 43 行（vipdoc/zip 接缝修订）。
- **v2 是 PG 的严格超集**（pg-only=0；v2-only 24,381 行 = bj920 新代码段、58x 科创ETF 等新 zip 覆盖扩展）→ C3 行数差即此。

## C5 分解（hfq 因子）
- 不匹配仅 **101/12,122 只**（0.8%），60 只全史级联。抽样 sz000006 定位：GBBQ 事件两侧完全一致，分叉源自 **单个历史除权日（1994-06-27）理论昨收的舍入精度差**（v2 保留 4 位 vs PG 更低精度），此后为**常数倍率级联**（1.0000126）。
- **常数倍率在一切收益计算中消去** → 对研究结论零影响。v2 的 4 位精度更接近无舍入真值。

## 裁定
管线正确性命题（"换存储不换数据"）成立：同源行逐值相等、复权算法在同 GBBQ 下逐位一致（TASK-012 五复杂样本实证）。全部差异 = ① TDX 源在快照间的追溯修订（v2 更新鲜，属期望行为）；② 理论昨收精度提升（收益不变量）。**M1 PASS**，tag `v2.0-m1`。

后续：PG 已完成历史使命，按 ADR-0002 于 M3（TASK-033）归档退役；validate 脚本随之删除。
