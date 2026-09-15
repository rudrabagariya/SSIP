# Load Cell Testing — HX711 + 4×50kg Load Cells on Raspberry Pi

## Wiring Diagram

```
┌──────────────────────────────────────────────────────┐
│                   Raspberry Pi                        │
│                                                       │
│   Pin 1  (3.3V) ─────────────── VCC  ┐               │
│   Pin 6  (GND)  ─────────────── GND  │  HX711        │
│   Pin 29 (GPIO 5) ───────────── DOUT │  Amplifier     │
│   Pin 31 (GPIO 6) ───────────── SCK  ┘               │
│                                                       │
└──────────────────────────────────────────────────────┘

HX711 Load Cell Side:
┌─────────────────────────────────────────────────────────┐
│                                                          │
│   E+  ──── Red wire (Excitation +)                       │
│   E-  ──── Black wire (Excitation -)                     │
│   A+  ──── White/Green wire (Signal +)  ← Channel A     │
│   A-  ──── Green/White wire (Signal -)                   │
│                                                          │
│   4×50kg load cells connected in Wheatstone bridge       │
│   Total capacity: 200kg                                  │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### ⚠️ Important: Use 3.3V, NOT 5V!
The Raspberry Pi GPIO pins are **3.3V tolerant only**. 
Using 5V for VCC still works for the HX711 amplifier, but the DOUT 
output may exceed 3.3V and damage the Pi. Stick with **3.3V** to be safe.

---

## Quick Start (3 Steps)

### Step 1: Test the wiring
```bash
cd load_cell_test
sudo python3 test_raw.py
```
This reads raw ADC values and checks if the HX711 is alive. 
If all readings are zero or timeout, fix your wiring first.

### Step 2: Calibrate with a known weight
```bash
sudo python3 calibrate.py
```
Interactive wizard:
1. Tares the empty platform
2. Asks you to place a known weight (e.g., 500g water bottle)
3. Calculates the conversion factor
4. Saves to `calibration.json`

### Step 3: Read weight continuously
```bash
sudo python3 read_weight.py
```
Shows live weight in grams/kg with stability detection.

---

## All Scripts

| Script | Purpose |
|--------|---------|
| `test_raw.py` | First-run diagnostic — verifies wiring and reads raw ADC values |
| `calibrate.py` | Interactive calibration wizard — creates `calibration.json` |
| `read_weight.py` | Continuous weight display with stability detection |
| `weight_monitor.py` | Event-based monitor — detects item placed/removed (integration preview) |
| `hx711.py` | Core HX711 driver module (imported by all scripts) |

---

## Custom GPIO Pins

All scripts default to **GPIO 5** (DOUT) and **GPIO 6** (SCK).
To use different pins:

```bash
sudo python3 calibrate.py --dout 17 --sck 27
sudo python3 read_weight.py --dout 17 --sck 27
```

---

## Troubleshooting

### HX711 not responding / all timeouts
- Check VCC → 3.3V (Pin 1)
- Check GND → GND (Pin 6, 9, 14, 20, 25, 30, 34, or 39)
- Verify DOUT and SCK are not swapped
- Confirm the HX711 LED is lit

### All readings are zero
- Load cells are not connected to HX711
- Check E+, E-, A+, A- wires from the Wheatstone bridge

### Very noisy readings (jumping wildly)
- Use shorter wires between load cells and HX711
- Use shielded cable for signal wires (A+, A-)
- Keep HX711 away from motors, relays, and power supplies
- Add a decoupling capacitor (100nF) between VCC and GND on the HX711

### Weight drifts over time
- Allow 5 minutes warm-up after power-on
- Ensure load cells are mechanically stable (bolted, not just resting)
- Re-tare periodically: `hx.tare()` in your code

### Calibration error > 5%
- Use a more accurate reference weight (kitchen scale verified)
- Take more samples: `sudo python3 calibrate.py --samples 30`
- Mount load cells on a rigid, flat surface

---

## 4-Load-Cell Wheatstone Bridge Wiring

If your 4 load cells each have 3 wires (Red, White, Black):

```
         ┌─── Cell 1 ───┐
         │   R   W   B   │
    E+ ──┤               ├── A+
         │               │
         ├─── Cell 2 ───┤
         │   R   W   B   │
    E- ──┤               ├── A-
         │               │
         ├─── Cell 3 ───┤
         │   R   W   B   │
         │               │
         └─── Cell 4 ───┘

    Red (R)   = Excitation
    White (W) = Signal
    Black (B) = Ground

    Full Bridge:
      E+ = Cell1.Red + Cell3.Red
      E- = Cell2.Red + Cell4.Red
      A+ = Cell1.White + Cell2.White  (or Cell1.White + Cell4.White)
      A- = Cell3.White + Cell4.White  (or Cell2.White + Cell3.White)
```

> **Note**: Load cell color codes vary by manufacturer. 
> If your cells have different wire colors, refer to the datasheet.
> A common 4-wire cell uses: Red (E+), Black (E-), Green (A+), White (A-).

---

## Next Steps (Integration with Kiosk)

Once calibration and testing are done:
1. The `weight_monitor.py` pattern (event-based detection) will be 
   integrated into `ui_main.py` to detect items placed on the checkout platform.
2. Each product's known weight (from `products.csv` → `weight_grams` column) 
   will be compared against the measured weight for verification.
