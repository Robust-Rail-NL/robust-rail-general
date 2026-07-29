# Kleine Binckhorst
This is a shunting yard near The Hague Central station in the Netherlands, its layout is visualized as follows (source: [SporenPlan online](https://sporenplan.nl/)):

![Kleine Binckhorst visualization](kleine_binckhorst.png)

### Details:
The incoming (gateway) track is RailRoad 906a (left bottom corner) which connects to a bumper (`Sein70`) and a switch (`Wissel963`), which is also indicated as 963 in Figure 1. This switch connects to RailRoad 906b. Track 906b in our location is not connected to track 51a, but instead ends with a bumper (`Stootblok906b`).

### Generating Custom Scenario Configurations:
To generate scenario configurations using the Kleine Binckhorst, you can use `custom_scenario_configs.py`. This produces `configurations/scenario_config_custom_<trains>_<instance>_<matching>.json` for every combination of trains x instances x matchings specified. These configurations can then be ingested by the generator to produce the specified scenarios.

#### Usage
All parameters can either be specified using a json file or using the command line.

```
python3 generate_experiment_configs.py -n 5 10 15 -i 5 -m FIFO random LIFO
python3 generate_experiment_configs.py --from-json example.json
```

Any flag passed on the command line overrides the same key from `--from-json`.

#### JSON file structure

All keys are optional — omitted keys fall back to the script's built-in
defaults. Below is an example json file.

```json
{
    "number_of_trains": [5, 10, 15, 20],
    "number_of_instances": 5,
    "matchings": ["FIFO", "random", "LIFO"],
    "seed": 42,
    "time_window_per_train": 360,
    "mixed_traffic": false,
    "min_gap_on_gateway": 180,
    "perform_servicing": false,
    "train_unit_types": ["VIRM-4", "VIRM-6", "ICM-3", "ICM-4", "SNG-3", "SNG-4", "SLT-4", "SLT-6"],
    "super_type_ratio": 0.5,
    "units_per_composition": [1, 2, 3],
    "matching_complexity": 0.3,
    "instanding_ratio": 0.3,
    "outstanding_ratio": 0.1
}
```

| Key | Type | Meaning |
|---|---|---|
| `number_of_trains` | list of int | Train counts to sweep over |
| `number_of_instances` | int | Instances to generate per (trains, matching) combo |
| `matchings` | list of `"FIFO"`\|`"random"`\|`"LIFO"` | Matching strategies to sweep over |
| `seed` | int | Base seed |
| `time_window_per_train` | int | Used to derive `end_time = trains * time_window_per_train` |
| `mixed_traffic` | bool | |
| `min_gap_on_gateway` | int | |
| `perform_servicing` | bool | |
| `train_unit_types` | list of str | |
| `super_type_ratio` | float | |
| `units_per_composition` | list of int | |
| `matching_complexity` | float | |
| `instanding_ratio` | float | |
| `outstanding_ratio` | float | |