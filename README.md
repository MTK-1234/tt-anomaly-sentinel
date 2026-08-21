![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Streaming Median-MAD Estimator

**Tiny Tapeout submission, SkyWater 130nm, TTSKY26c shuttle**

- [Read the full project documentation](docs/info.md)

## What is this?
---

This project is an ultra-low-area, zero-RAM statistical co-processor implemented in Verilog. The design tracks baseline and volatility to classify time-series anomalies like drift, glitches, and stuck sensors in real-time.

The sentinel receives an 8-bit input data stream. It combines a streaming median and MAD (Median Absolute Deviation) tracker with a Temporal Persistence Engine. It operates entirely without memory buffers, utilizing continuous digital feedback loops to distinguish between transient outliers and persistent baseline shifts.

**Research contribution:** This project demonstrates deterministic statistical analysis (Median and MAD) and complex event classification entirely without the use of RAM arrays, hardware multipliers, or dividers. This makes it exceptionally area and power efficient for Edge IoT sensors.

## Design summary
---

- **Top module:** `tt_um_MTK1234_anomaly_sentinel`
- **Real device count:** ~600 standard cells (post-LVS, SkyWater 130nm sky130_fd_sc_hd)
- **Clock:** 50 MHz (20ns period)
- **Verified:** DRC, LVS, and Antenna checks clean via LibreLane and Tiny Tapeout CI pipeline
- **Verification:** cocotb regression covering configuration, baseline saturation, transient glitches, baseline shifts, momentum drift, and stuck-sensor hardware faults

## What is Tiny Tapeout?
---

Tiny Tapeout is an educational project that aims to make it easier and cheaper than ever to get your digital and analog designs manufactured on a real chip.

To learn more, visit https://tinytapeout.com.

## Resources
---

- [FAQ](https://tinytapeout.com/faq/)
- [Digital design lessons](https://tinytapeout.com/digital_design/)
- [Build your design locally](https://www.tinytapeout.com/guides/local-hardening/)

## What next?

- [Submit your design to the next shuttle](https://app.tinytapeout.com/).
- Edit [this README](README.md) and explain your design, how it works, and how to test it.
- Share your project on your social network of choice:
  - LinkedIn [#tinytapeout](https://www.linkedin.com/search/results/content/?keywords=%23tinytapeout) [@TinyTapeout](https://www.linkedin.com/company/100708654/)
  - Mastodon [#tinytapeout](https://chaos.social/tags/tinytapeout) [@matthewvenn](https://chaos.social/@matthewvenn)
  - X (formerly Twitter) [#tinytapeout](https://twitter.com/hashtag/tinytapeout) [@tinytapeout](https://twitter.com/tinytapeout)
  - Bluesky [@tinytapeout.com](https://bsky.app/profile/tinytapeout.com)
