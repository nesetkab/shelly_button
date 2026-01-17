import asyncio
import time
from bleak import BleakScanner
import Quartz
from ScriptingBridge import SBApplication

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


# --- Slide Configuration ---
# Normal slides (non-CYOA): button 4 goes back, button 1 advances
NORMAL_SLIDES = {
    1,
    2,
    3,
    4,
    5,
    11,
    12,
    13,
    14,
    15,
    21,
    27,
    28,
    29,
    30,
    31,
    32,
    38,
    44,
    45,
    51,
    52,
}

# CYOA choice slides (first slide of each CYOA group): buttons 1-4 jump to outcomes
CYOA_CHOICE_SLIDES = {6, 16, 22, 33, 39, 46}

# CYOA outcome slides: button 1 jumps to next section, button 4 goes back to choice slide
# Format: outcome_slide: (choice_slide, next_normal_slide)
CYOA_OUTCOME_SLIDES = {
    # Group 6-10: choice=6, next=11
    7: (6, 11),
    8: (6, 11),
    9: (6, 11),
    10: (6, 11),
    # Group 16-20: choice=16, next=21
    17: (16, 21),
    18: (16, 21),
    19: (16, 21),
    20: (16, 21),
    # Group 22-26: choice=22, next=27
    23: (22, 27),
    24: (22, 27),
    25: (22, 27),
    26: (22, 27),
    # Group 33-37: choice=33, next=38
    34: (33, 38),
    35: (33, 38),
    36: (33, 38),
    37: (33, 38),
    # Group 39-43: choice=39, next=44
    40: (39, 44),
    41: (39, 44),
    42: (39, 44),
    43: (39, 44),
    # Group 46-50: choice=46, next=51
    47: (46, 51),
    48: (46, 51),
    49: (46, 51),
    50: (46, 51),
}
# ------------------------------------------

# --- Debounce ---
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

# Dictionary to store the state of each button device we find
devices = {}


def send_key(key_code):
    """Send a keyboard key press."""
    event = Quartz.CGEventCreateKeyboardEvent(None, key_code, True)  # key down
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
    event = Quartz.CGEventCreateKeyboardEvent(None, key_code, False)  # key up
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def get_keynote():
    """Get Keynote application and document."""
    try:
        keynote = SBApplication.applicationWithBundleIdentifier_(
            "com.apple.iWork.Keynote"
        )
        if keynote and keynote.documents():
            return keynote, keynote.documents()[0]
    except:
        pass
    return None, None


def get_current_slide():
    """Get the current slide number from Keynote via ScriptingBridge."""
    try:
        _, doc = get_keynote()
        if doc:
            return doc.currentSlide().slideNumber()
    except Exception as e:
        print(f"Failed to get slide: {e}")
    return None


def jump_to_slide(slide_num):
    """Jump to a specific slide in Keynote."""
    try:
        keynote, doc = get_keynote()
        if doc:
            slides = doc.slides()
            if 0 < slide_num <= len(slides):
                target_slide = slides[slide_num - 1]
                doc.setCurrentSlide_(target_slide)
                print(f"Jumped to slide {slide_num}")
                return True
    except Exception as e:
        print(f"Failed to jump to slide: {e}")
    return False


def is_debounced(button_num):
    """Check if button press should be debounced. Returns True if too fast."""
    current_time = time.monotonic()
    if (current_time - LAST_PRESS_TIME[button_num]) < DEBOUNCE_SECONDS:
        print(f"Button {button_num} debounced (too fast).")
        return True
    LAST_PRESS_TIME[button_num] = current_time
    return False


def next_slide():
    """Advance to the next slide (sends right arrow key)."""
    print("Advancing to next slide.")
    send_key(124)  # 124 = right arrow key


def prev_slide():
    """Go back to previous slide (sends left arrow key)."""
    print("Going back one slide.")
    send_key(123)  # 123 = left arrow key


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

                    # Get the event type (press, long_press, etc.)
                    event_type = event_obj.event_type

                    if event_type is not None:
                        # Determine button number
                        button_num = None
                        if button_key == "button_1":
                            button_num = 1
                        elif button_key == "button_2":
                            button_num = 2
                        elif button_key == "button_3":
                            button_num = 3
                        elif button_key == "button_4":
                            button_num = 4

                        if button_num and not is_debounced(button_num):
                            current_slide = get_current_slide()

                            if current_slide in NORMAL_SLIDES:
                                # Normal slides: 1=next, 4=back
                                if button_num == 1:
                                    if current_slide == 51:
                                        jump_to_slide(1)  # Restart
                                    else:
                                        next_slide()
                                elif button_num == 4:
                                    prev_slide()

                            elif current_slide in CYOA_CHOICE_SLIDES:
                                # CYOA choice slides: buttons jump to outcome slides
                                jump_to_slide(current_slide + button_num)

                            elif current_slide in CYOA_OUTCOME_SLIDES:
                                # CYOA outcome slides: 1=jump to next section, 4=back to choice
                                choice_slide, next_section = CYOA_OUTCOME_SLIDES[
                                    current_slide
                                ]
                                if button_num == 1:
                                    jump_to_slide(next_section)
                                elif button_num == 4:
                                    jump_to_slide(choice_slide)
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
