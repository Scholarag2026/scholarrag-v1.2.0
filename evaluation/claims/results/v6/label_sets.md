## Table E2-i Verifier against every label set

- `human_blind`: three labellers, blind, label of record
- `construction_rule`: construction rule, constructed set only

| Label set | Population | Run | n | no majority | Correct | Accuracy | Wilson 95% | Kappa | Verified precision | Verified recall | Falsely verified |
|---|---|---|---|---|---|---|---|---|---|---|---|
| human_blind | constructed | A | 60 | 0 | 53 | 0.883 | [0.778, 0.942] | 0.829 | 0.929 | 0.867 | 1 |
| human_blind | constructed | B | 60 | 0 | 52 | 0.867 | [0.758, 0.931] | 0.805 | 0.923 | 0.800 | 1 |
| human_blind | real | A | 26 | 0 | 15 | 0.577 | [0.389, 0.745] | 0.360 | 1.000 | 0.462 | 0 |
| human_blind | real | B | 26 | 0 | 15 | 0.577 | [0.389, 0.745] | 0.360 | 1.000 | 0.462 | 0 |
| human_blind | all | A | 86 | 0 | 68 | 0.791 | [0.693, 0.863] | 0.705 | 0.950 | 0.679 | 1 |
| human_blind | all | B | 86 | 0 | 67 | 0.779 | [0.681, 0.854] | 0.689 | 0.947 | 0.643 | 1 |
| construction_rule | constructed | A | 60 | 0 | 55 | 0.917 | [0.819, 0.964] | 0.878 | 1.000 | 0.875 | 0 |
| construction_rule | constructed | B | 60 | 0 | 54 | 0.900 | [0.799, 0.953] | 0.854 | 1.000 | 0.812 | 0 |

## Agreement between label sets

| Set A | Set B | Population | n | no majority | Agree | Kappa |
|---|---|---|---|---|---|---|
| human_blind | construction_rule | constructed | 60 | 0 | 58 | 0.952 |
