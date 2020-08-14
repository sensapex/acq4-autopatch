# coding: utf8
import json
import sys

import numpy as np
import pyqtgraph as pg

# get name of log file from command line
logfile = sys.argv[1]

# load and parse log events
log = [json.loads(line) for line in open(logfile).readlines()]
log = [ev for ev in log if "event_time" in ev]
start_time = log[0]["event_time"]
end_time = log[-1]["event_time"]

# make a list of times for all state changes
state_events = [ev for ev in log if ev["event"] == "state_change"]
states = []
for i, ev in enumerate(state_events):
    if i < len(state_events) - 1:
        state_end = state_events[i + 1]["event_time"]
    else:
        state_end = end_time
    states.append((ev["state"], ev["event_time"], state_end))
    last_state_event = ev

# make an array of pressure changes
pressure_events = [event for event in log if event["event"] == "pressure_changed"]
pressure_data = np.empty(len(pressure_events), dtype=[("event_time", float), ("pressure", float), ("source", object)])
for i, ev in enumerate(pressure_events):
    pressure_data[i] = (ev["event_time"], ev["pressure"], ev["source"])

# make an array holding all test pulse data
test_pulse_events = [event for event in log if event["event"] == "test_pulse"]
dtype = [(k, float) for k, v in test_pulse_events[0].items() if isinstance(v, (float, int))]
test_pulse_data = np.empty(len(test_pulse_events), dtype=dtype)
for i, event in enumerate(test_pulse_events):
    for k, t in dtype:
        test_pulse_data[i][k] = event[k]

# which test pulse parameters to plot?
plot_params = [
    ("peakResistance", "Ω"),
    ("steadyStateResistance", "Ω"),
    # ('fitExpAmp', 'V'),
    # ('fitExpTau', 's'),
    # ('capacitance', 'F'),
    ("baselineCurrent", "A"),
    ("baselinePotential", "V"),
]

# set up plot window
app = pg.mkQApp()
win = pg.GraphicsLayoutWidget()
state_plot = win.addPlot()
state_plot.setMouseEnabled(True, False)
state_plot.enableAutoRange(True, False)
win.nextRow()
pressure_plot = win.addPlot(labels={"left": ("pressure", "Pa"), "bottom": ("time", "s")})
pressure_plot.setXLink(state_plot)
plots = {}
for param, unit in plot_params:
    win.nextRow()
    plots[param] = win.addPlot(labels={"left": (param, unit), "bottom": ("time", "s")})
    plots[param].setXLink(state_plot)
win.resize(1000, 1000)
win.show()

# plot state changes
state_rgns = []
for state, start, end in states:
    rgn = pg.LinearRegionItem([start - start_time, end - start_time], movable=False)
    state_plot.addItem(rgn)
    label = pg.TextItem(state, angle=90)
    label.setPos(start - start_time, 0)
    state_plot.addItem(label)

    state_rgns.append(rgn)

# plot pressure
pressure_plot.plot(pressure_data["event_time"] - start_time, pressure_data["pressure"][:-1], stepMode=True)
pressure_rgns = []

# plot test pulse data
time = test_pulse_data["event_time"] - start_time
for param, unit in plot_params:
    if param not in test_pulse_data.dtype.names:
        raise ValueError(f"No test pulse field named {param!r}; options are {test_pulse_data.dtype.names!r}")
    plots[param].plot(time, test_pulse_data[param])

# start qt event loop unless we are running interactive already
if sys.flags.interactive == 0:
    app.exec_()
