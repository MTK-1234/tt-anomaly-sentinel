## How it works

This is an ultra-low-area Event-Driven Sensor Sentinel. It combines a streaming median and MAD (Median Absolute Deviation) tracker with a Temporal Persistence Engine to distinguish between transient outliers and persistent baseline shifts. It operates entirely without memory buffers, tracking DC offset, noise width, and innovation correlation simultaneously.

## How to test

Apply an 8-bit signal to the input pins (`ui_in`). 
- A flat signal will output a `000` event code on `uio_out[2:0]`. 
- Injecting a massive 1-cycle spike will output a `001` (Hold/Glitch) interrupt code. 
- Injecting a permanent shift in the baseline will output a `010` (Shift) interrupt code, causing the internal tracker to enter COARSE mode.
