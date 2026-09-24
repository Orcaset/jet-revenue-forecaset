# Revenue Forecaset with Jev

This model builds a revenue forecast for 1,000 in-place clients using a bottoms-up approach. It queries Jev inline to determine contract renewal details from client history and CRM notes.

## Run the model

Requires an env var or `.env` file with a `TYPESAFE_API_KEY`.

```sh
uv sync
uv run main.py
```

## How it Works

[`data/clients.json`](data/clients.json) holds simulated details for 1,000 clients. It includes first contract year, opening or current contract details, CRM notes, and the client's trailing twelve month usage growth.

Revenue is built out on a per-contract basis and rolled up into total revenue. At each contract roll date, Jev decides whether a client renews. If the client does renew, Jev also returns change in ACV using bucketed choices. If the client does not renew, Jev selects a reason for termination.

Forecasts for each contract are built as lazy [Orcaset](https://github.com/orcaset/orcaset-py) `Series`, so Jev decisions are fetched on-demand in response to end-user queries.

In addition to typical cohort-based runoff tables, you can also do more novel things like grouping by termination cause by using Jev to categorize likely drivers.

## Perfomance

Total time to execute `main.py` has ranged from as little as 2.8 seconds to as much as 112 seconds. The range is presumably due to TypeSafe AI rate limiting some requests to manage demand.

## Output

Client contract-level forecasts in the following form.

```txt
Start                              2025-12-31  2026-12-31  2027-12-31
End                    2025-12-31  2026-12-31  2027-12-31  2028-12-31
Marten Gaming revenue               18,100.00   20,338.17   27,150.00 
```

By client cohort.

```txt
Start                         2025-12-31     2026-12-31     2027-12-31
End            2025-12-31     2026-12-31     2027-12-31     2028-12-31
  2015 cohort                 371,400.00     363,262.37     362,800.00
  2016 cohort                 497,347.02     529,393.44     496,930.00
  2017 cohort                 692,111.63     646,614.89     578,578.41
  2018 cohort               2,377,075.32   2,496,301.81   2,301,757.88
  2019 cohort               2,294,996.60   2,517,457.19   2,540,047.05
  2020 cohort               2,862,347.41   3,032,764.43   2,938,576.22
  2021 cohort               4,341,860.21   4,615,166.60   4,500,034.31
  2022 cohort               4,964,608.03   5,127,572.70   5,163,039.38
  2023 cohort               7,948,855.70   8,596,118.21   8,150,716.62
  2024 cohort               6,982,795.14   8,101,824.74   8,015,933.07
  2025 cohort               6,786,025.18   8,189,791.30   8,137,122.80
----------------------------------------------------------------------
Total revenue              45,329,793.81  54,603,454.70  53,365,792.52
```

Cumulative dollar churn by termination reason.

```txt
Start                                        2025-12-31    2026-12-31    2027-12-31
End                            2025-12-31    2026-12-31    2027-12-31    2028-12-31
  budget_cut                         0.00  1,154,700.00  2,473,200.00  3,315,800.00
  lost_champion                      0.00    515,300.00  1,314,700.00  1,668,400.00
  competitor                         0.00    318,300.00    681,700.00    904,500.00
  low_adoption                       0.00     97,200.00    214,400.00    611,200.00
  unclear                            0.00    277,700.00    472,700.00    524,200.00
-----------------------------------------------------------------------------------
Total cumulative lost revenue        0.00  2,363,200.00  5,156,700.00  7,024,100.00
```