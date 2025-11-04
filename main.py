import asyncio
import time  # <-- ADD THIS MODULE
from bleak import BleakScanner
from pynput.keyboard import Controller, Key

# NEW: Import only the classes we need
from bthome_ble import (
    BTHomeBluetoothDeviceData,
)
from dataclasses import dataclass
from typing import Any

# NEW: Import datetime to fix the 'time' attribute error
from datetime import datetime, timezone


@dataclass
class WrapperBluetoothServiceInfo:
    """
    A simple wrapper class to hold data from bleak
    in the format bthome-ble expects.
    This replaces the Home Assistant-specific BluetoothServiceInfo.
    """

    name: str | None
    address: str
    service_data: dict[str, bytes]
    manufacturer_data: dict[int, bytes]
    rssi: int | None
    tx_power: int | None
    # NEW: Add the time attribute
    time: datetime | None

    def as_dict(self) -> dict[str, Any]:
        """Helper function for debugging, not actively used."""
        return {
            "name": self.name,
            "address": self.address,
            "service_data": self.service_data,
            "manufacturer_data": self.manufacturer_data,
            "rssi": self.rssi,
            "tx_power": self.tx_power,
            # NEW: Include 'time' in the dict
            "time": self.time,
        }


# --- Customize Your Key Mappings Here ---
# Map button number (1, 2, 3, 4) to a key.
# Use 'a', 'b', etc. for letter keys.
# For special keys (like Enter, F1, media keys), use 'Key.enter', 'Key.f1', 'Key.media_play_pause'.
KEY_MAPPING = {
    1: Key.up,
    2: Key.down,
    3: Key.left,
    4: Key.right,
}
# ------------------------------------------

# --- ADD DEBOUNCE LOGIC ---
# Cooldown period in seconds to prevent double-clicks
DEBOUNCE_SECONDS = 1
# Dictionary to store the timestamp of the last press for each button
LAST_PRESS_TIME = {
    1: 0.0,
    2: 0.0,
    3: 0.0,
    4: 0.0,
}
# --------------------------

# Full UUID for BTHome service
BTHOME_SERVICE_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"

# Global keyboard controller
keyboard = Controller()

# Dictionary to store the state of each button device we find
# This prevents spamming keys by only reporting *new* events
devices = {}


def handle_key_press(button_num):
    """Handles the logic for pressing a key, with debouncing."""
    # --- ADD DEBOUNCE CHECK ---
    current_time = time.monotonic()

    if (current_time - LAST_PRESS_TIME[button_num]) < DEBOUNCE_SECONDS:
        # If it's too soon since the last press, ignore this event
        print(f"Button {button_num} press debounced (too fast).")
        return

    # --- END DEBOUNCE CHECK ---

    if button_num in KEY_MAPPING:
        key_to_press = KEY_MAPPING[button_num]
        print(f"Button {button_num} press detected. Emulating key: {key_to_press}")

        # --- UPDATE LAST PRESS TIME ---
        LAST_PRESS_TIME[button_num] = current_time
        # --- END UPDATE ---

        # Tap the key (press and release)
        keyboard.tap(key_to_press)
    else:
        print(f"Button {button_num} press detected, but no key mapping found.")


def detection_callback(device, advertisement_data):
    """Called by Bleak for every BLE advertisement found."""

    # Check if the device is advertising BTHome data
    if BTHOME_SERVICE_UUID in advertisement_data.service_data:
        # Convert address to string immediately
        address = str(device.address)

        # If this is a new device, create a state-tracking object for it
        if address not in devices:
            print(f"Found new BTHome device: {address} ({device.name})")
            devices[address] = BTHomeBluetoothDeviceData()

        # Create our wrapper object with all the data bthome-ble needs
        service_info = WrapperBluetoothServiceInfo(
            name=str(device.name) if device.name else None,
            address=address,
            service_data=advertisement_data.service_data,
            manufacturer_data=advertisement_data.manufacturer_data,
            rssi=None,  # device.rssi is not reliable on all platforms
            tx_power=None,  # advertisement_data.tx_power is not reliable
            # NEW: Add the current timestamp
            time=datetime.now(timezone.utc),
        )

        # --- THIS IS THE FIX ---

        # Now we pass the correctly structured 'service_info' object.
        # The update() method returns a single SensorUpdate object.
        sensor_update = devices[address].update(service_info)

        if sensor_update:
            # DEBUG: Print the raw update object we get from the library
            # print(f"Got update: {sensor_update}")

            # Check the .events attribute of the sensor_update object
            # This attribute is a dictionary.
            if sensor_update.events:
                # print(f"Found events: {sensor_update.events}")

                # Iterate over the event *objects* in the dictionary's values
                for event_obj in sensor_update.events.values():
                    # --- THIS IS THE FINAL FIX ---

                    # Get the button key (e.g., 'button_1', 'button_2', 'button_3', 'button_4')
                    button_key = event_obj.device_key.key

                    # Check if the event type is a valid press (not None)
                    # This will catch "press", "double_press", "hold_press", etc.
                    if event_obj.event_type is not None:
                        # THE VERY FINAL FIX: Check for "button_1" not "button"
                        if button_key == "button_1":
                            handle_key_press(1)
                        elif button_key == "button_2":
                            handle_key_press(2)
                        elif button_key == "button_3":
                            handle_key_press(3)
                        elif button_key == "button_4":
                            handle_key_press(4)
                    # else:
                    # print(f"Ignoring 'None' event on {button_key}")

                    # --- END OF FINAL FIX ---
        # else:
        # DEBUG: Uncomment this line to see if we're getting data but no *new* events
        # print(f"Got BTHome data from {address}, but no new events.")
        # --- END OF FIX ---


async def main():
    """Main function to start and run the scanner."""
    print("Starting BLE scanner to listen for Shelly BTHome buttons...")
    print("Press Ctrl+C to stop.")

    # Create and start the scanner
    # The detection_callback will be called for each device found
    scanner = BleakScanner(detection_callback=detection_callback)

    try:
        await scanner.start()

        # Keep the script running indefinitely
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("Stopping scanner...")
    finally:
        await scanner.stop()
        print("Scanner stopped.")


if __name__ == "__main__":
    asyncio.run(main())
