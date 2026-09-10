# Expected plan

Train 11111 arrives first with in front unit 2101 which requires servicing.
Split 11111 on rail4, then service the front unit on rail1. 
Meanwhile train 11112 arrives on rail4, couple with 2102. 
Then, unit 2101 to rail3, combine with units 2102 and 2103.
Meanwhile, train 22222 arrives on rail4, move it to rail5.
Finally, train 33333 arrives on rail4, which must be serviced on rail1.
Then, it departs again as train 33334.
Then, train 22222 departs as train 22223, requiring a saw movement on rail1.
Finally, train 11113 departs with three train units from rail3.

## Problems found in solver
```
HIP 2.0.0
Using config file: config.yaml
***************** Reading Location and Scenario *****************
Parsing JSON location from ../../robust-rail-general/Location_SimpleService/location.json
Parsing JSON scenario from ../../robust-rail-general/Location_SimpleService/scenarios/scenario_full_example.json
The Location file parsing was successful
    Location with 5 tracks and 11 track parts, including 5 parking tracks, 2 crossings and 1 servicing tracks
The Scenario file parsing was successful
    Scenario with 4 incoming trains 3 outgoing trains, 0 instanding trains 0 outstanding trains.
    Number of train units 7 of different train unit types 18: VIRM (0 units), VIRM (0 units), DDZ (0 units), DDZ (0 units), SLT (3 units), SLT (0 units), ICM (1 units), ICM (1 units), ICR (0 units), ICR (0 units), FFF (0 units), FFF (0 units), SNG (1 units), SNG (1 units), SGMM (0 units), SGMM (0 units), ICNG (0 units), ICNG (0 units)
Scenario details: 
---- Incoming Trains ----
Arrival track 4 for train (id) 11111 at time 500
Arrival track 4 for train (id) 11112 at time 1300
Arrival track 4 for train (id) 22222 at time 1500
Arrival track 4 for train (id) 33333 at time 1700
---- Outgoing Trains ----
Departure track 4 for train (id) 33334 at time 2800
Departure track 4 for train (id) 22223 at time 3000
Departure track 4 for train (id) 11113 at time 3300
***************** Creating a Plan *****************
Using randomly generated seed <-1313205710>.
Parsing JSON location from ../../robust-rail-general/Location_SimpleService/location.json
Parsing JSON scenario from ../../robust-rail-general/Location_SimpleService/scenarios/scenario_full_example.json
Create Plan Iteration: 0
Split part shunt train (2101,2102) to (2101,2102)
Split part shunt train (2103) to (2103)
Split part shunt train (2201,2202) to (2201),(2202)
Split part shunt train (2301,2302) to (2301),(2302)
Add routing task (2101,2102): 4->? from arrival on track 4 rail_4 (420 A) at time 00:08:20--00:08:20
Add routing task (2103): 4->? from arrival on track 4 rail_4 (420 A) at time 00:21:40--00:21:40
Add routing task (2201,2202): 4->? from arrival on track 4 rail_4 (420 A) at time 00:25:00--00:25:00
Add routing task (2301,2302): 4->? from arrival on track 4 rail_4 (420 A) at time 00:28:20--00:28:20
<Intial> Add 1th move task (2101,2102): 4->? at time 00:08:20--00:08:20
<Intial> Add 2th move task (2101,2102): ?->1A at time 00:08:20--00:08:20
<Intial> Add 3th move task (2101,2102): 1->? at time 00:16:40--00:16:40
<Intial> Add 4th move task (2103): 4->? at time 00:21:40--00:21:40
<Intial> Add 5th move task (2201,2202): 4->? at time 00:25:00--00:25:00
<Intial> Add 6th move task (2301,2302): 4->? at time 00:28:20--00:28:20
<Intial> Add 7th move task (2301): ?->1A at time 00:28:20--00:28:20
<Intial> Add 8th move task (2301): 1->? at time 00:36:40--00:36:40
<Intial> Add 9th move task (2302): ?->1A at time 00:36:40--00:36:40
<Intial> Add 10th move task (2302): 1->? at time 00:45:00--00:45:00
<Intial> Add 11th move task ((2302,2301) ?None->4A : ) at time 00:46:40--00:46:40
<Intial> Add 12th move task ((2202,2201) ?None->4A : ) at time 00:50:00--00:50:00
<Intial> Add 13th move task ((2101,2102,2103) ?None->4A : ) at time 00:55:00--00:55:00
Set parking track on routing (2101,2102): 4->3B to parking track 3 rail_3 (420 B)
Set parking track on routing (2101,2102): 1->1A to parking track 1 rail_1 (1000 Both)
Set parking track on routing (2103): 4->1A to parking track 1 rail_1 (1000 Both)
Set parking track on routing (2201,2202): 4->1A to parking track 1 rail_1 (1000 Both)
Set parking track on routing (2301,2302): 4->2B to parking track 2 rail_2 (420 B)
Set parking track on routing (2301): 1->3B to parking track 3 rail_3 (420 B)
Set parking track on routing (2302): 1->3B to parking track 3 rail_3 (420 B)
Process terminated. Assertion failed.
   at ServiceSiteScheduling.Solutions.PlanGraph.CheckGraphStructure(Dictionary`2 seen_mt, HashSet`1 seen_tt) in /Users/issahanou/Work/code/RobustRailNL/robust-rail-solver/ServiceSiteScheduling/Solutions/PlanGraph.cs:line 2017
   at ServiceSiteScheduling.Solutions.PlanGraph.IsWellFormed() in /Users/issahanou/Work/code/RobustRailNL/robust-rail-solver/ServiceSiteScheduling/Solutions/PlanGraph.cs:line 1943
   at ServiceSiteScheduling.Initial.SimpleHeuristic.Construct(Random random, Int32 debugLevel) in /Users/issahanou/Work/code/RobustRailNL/robust-rail-solver/ServiceSiteScheduling/Initial/SimpleHeuristic.cs:line 645
   at ServiceSiteScheduling.LocalSearch.TabuSearch..ctor(Random random, Int32 debugLevel) in /Users/issahanou/Work/code/RobustRailNL/robust-rail-solver/ServiceSiteScheduling/LocalSearch/TabuSearch.cs:line 18
   at ServiceSiteScheduling.Program.CreatePlan(String location_path, String scenario_path, String plan_path, Config config, Int32 debugLevel, String tmp_plan_path) in /Users/issahanou/Work/code/RobustRailNL/robust-rail-solver/ServiceSiteScheduling/Program.cs:line 164
   at ServiceSiteScheduling.Program.Main(String[] args) in /Users/issahanou/Work/code/RobustRailNL/robust-rail-solver/ServiceSiteScheduling/Program.cs:line 59
```

## Problems found in planner

- Get an `end_move_su` after `arrive_su`
  - Fix: remove `allowed_to_move_su` from `arrive_su` effects
  - Note: currently required for uncoupling
- `arrive_su`, let's a later arrival arrive first
  - Fix: removed two lines:
    ```
    for su in ordered_arrival_sus:
    problem.set_initial_value(su_previous_arrived(su), True)
    ```
  - increase lenghts of rail2/3/4/5 in LocationSimpleService to 420 to fit longer trains
- `concurrent_movements` is increased after arrive, not allowing `start_move_su` to activate
  - Removing this effect would allow the arrival of the next train straight away...
- Note: from `rail_4` move only to `rail_1` in the middle, then an extra action to the each of the other tracks from there
  - after moving to aside `rail_1` can then move to either aside on rail 2 or 3 or Bside of rail 4 or 5
- expected uncouple action after arriving, requires `allowed_to_move`
    - Fix: change precondition to `su_may_move`
- uncouple front and back have `(<= 2 (su_unit_count ?parent_su))`
  - Fix: back must have >2 otherwise always uncouple the front
- should change to consistent use of `(decrease (concurrent_movements) 1)` and `(increase (concurrent_movements) 1)`
- uncoupling requires `(not (allowed_to_move_su))`
- servicing requires `(not (allowed_to_move_su))`

### Servicing and Coupling  
Seem to be bigger problems with servicing and (un)coupling:
- Currently must service before uncoupling
- Services whole train even if only one unit requires servicing. 
- require servicing should be put on the trainunit or only on the shunting unit if all units require servicing
- currently, even when first train11111 is serviced then moved to track3 then train11112 joins on track3, the request is not active and they can currently not be combined, which is also a problem


