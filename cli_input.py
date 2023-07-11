import atexit
import json
import sys
import termios
import tty
from getpass import getpass
from itertools import zip_longest

from functions import *


def get_user_input(verbose_kernel: bool, skip_device: bool = False) -> dict:
    output_dict = {
        "distro_name": "",
        "distro_version": "",
        "de_name": "",
        "shell": "",
        "username": "",
        "password": "",
        "device": "image",
        "kernel_type": ""
    }
    # Print welcome message
    print_header("Welcome to Depthboot, formerly known as Breath\n"
                 "This script will create a bootable Linux image.\n"
                 "You can press Ctrl+C at any time to stop the script.\n"
                 "Select the default options if you are unsure.")
    input("Press Enter to continue...")

    # open os_sizes.json
    with open("os_sizes.json", "r") as f:
        os_sizes = json.load(f)

    while True:
        distro_name = ia_selection("Which Linux distribution (flavor) would you like to use?",
                                   options=["Fedora", "Ubuntu", "Pop!_OS", "Linux Mint (Cinnamon edition)", "Arch",
                                            "Generic ISO"],
                                   flags=[f"~{os_sizes['fedora_average']}GB (recommended)",
                                          f"~{os_sizes['ubuntu_average']}GB",
                                          f"{os_sizes['pop-os_22.04']['cosmic-gnome']}GB",
                                          f"{os_sizes['ubuntu_22.04']['cinnamon']}GB",
                                          f"{os_sizes['arch_latest']['cli']}GB",
                                          "(NOT recommended)"])
        skip_de_selection = False
        match distro_name:
            case "Ubuntu":
                output_dict["distro_name"] = "ubuntu"
                output_dict["distro_version"] = ia_selection("Which Ubuntu version would you like to use?",
                                                             options=["23.04", "22.04"], flags=[
                        f"{os_sizes['ubuntu_23.04']['cli']}GB (latest, recommended)",
                        f"{os_sizes['ubuntu_22.04']['cli']}GB (LTS version)"])
                break
            case "Linux Mint (Cinnamon edition)":
                output_dict["distro_name"] = "ubuntu"
                output_dict["distro_version"] = "22.04"
                output_dict["de_name"] = "cinnamon"
                print_warning("This option does *NOT* actually install Linux Mint. Instead it will install Ubuntu "
                              "22.04 (which is what Linux Mint is based on) with the Cinnamon desktop environment.")
                user_selection = ia_selection("Are you sure you want to continue?", options=["No", "Yes"], )
                if user_selection == "Yes":
                    skip_de_selection = True
                    break
            case "Arch":
                output_dict["distro_name"] = "arch"
                output_dict["distro_version"] = "latest"
                break
            case "Fedora":
                output_dict["distro_name"] = "fedora"
                output_dict["distro_version"] = ia_selection("Which Fedora version would you like to use?",
                                                             options=["38", "39"],
                                                             flags=[f"~{os_sizes['fedora_38']['cli']}GB "
                                                                    f"(stable, recommended)",
                                                                    f"~{os_sizes['fedora_39']['cli']}GB"
                                                                    " (beta, unrecommended)"])
                break
            case "Pop!_OS":
                output_dict["distro_name"] = "pop-os"
                output_dict["distro_version"] = "22.04"
                break
            case "Generic ISO":
                print_error("Please strongly consider using a supported distro, as generic ISO installs are not "
                            "optimized in any way. Generic installs will not get any kernel updates or Chromebook "
                            "specific fixes from the Eupnea team.")
                print_error("Keep in mind that this will not create a live iso, but rather a real system install, "
                            "which can be optionally installed to internal or be used from the usb/sd card directly.")
                while True:
                    user_selection = ia_selection("Are you sure you want to continue?", options=["No", "Yes"], )
                    if user_selection == "No":
                        print_warning("Exiting...")
                        print_header('Restart the script with: "./main.py" if you want to use a supported distro.')
                        sys.exit(0)
                    break
                print_error("Generic ISO installs are not supported by the Eupnea team. Issues/support tickets for "
                            "generic installs will be auto-closed immediately.\n"
                            "This script does NOT guarantee that the image will boot and you might have to manually "
                            "debug and fix the issue **YOURSELF**")
                while True:
                    user_selection = ia_selection("Are you sure you want to continue?", options=["No", "Yes"], )
                    if user_selection == "No":
                        print_warning("Exiting...")
                        print_header('Restart the script with: "./main.py" if you want to use a supported distro.')
                        sys.exit(0)
                    break
                output_dict["distro_name"] = "generic"
                output_dict["distro_version"] = "generic"
                output_dict["de_name"] = "generic"
                break
    print(f"{output_dict['distro_name']} {output_dict['distro_version']} selected")

    temp_distro_name = f'{output_dict["distro_name"]}_{output_dict["distro_version"]}'

    if output_dict["distro_name"] not in ["pop-os", "generic"] and not skip_de_selection:
        de_list = ["Gnome", "KDE", "Xfce", "LXQt", "Cinnamon"]
        flags_list = [f"(recommended) +{os_sizes[temp_distro_name]['gnome']}GB",
                      f"(recommended) +{os_sizes[temp_distro_name]['kde']}GB",
                      f"(recommended for weak devices) +{os_sizes[temp_distro_name]['xfce']}GB",
                      f"(recommended for weak devices) +{os_sizes[temp_distro_name]['lxqt']}GB",
                      f"+{os_sizes[temp_distro_name]['cinnamon']}GB"]
        match output_dict["distro_name"]:
            case "ubuntu":
                if output_dict["distro_version"] == "22.04":
                    de_list.append("deepin")
                    flags_list.append(f"+{os_sizes[temp_distro_name]['deepin']}GB")
                de_list.append("budgie")
                flags_list.append(f"+{os_sizes[temp_distro_name]['budgie']}GB")
            case "arch":
                # Deepin is currently broken on arch
                # de_list.extend(["deepin", "budgie"])
                de_list.append("budgie")
                flags_list.append(f"+{os_sizes[temp_distro_name]['budgie']}GB")
            case "fedora":
                de_list.extend(["deepin", "budgie"])
                flags_list.append(f"+{os_sizes[temp_distro_name]['deepin']}GB")
                flags_list.append(f"+{os_sizes[temp_distro_name]['budgie']}GB")

        de_list.append("cli")  # add at the end for better ux
        flags_list.append(f"+0GB")

        while True:
            desktop_env = ia_selection("Which desktop environment (Desktop GUI) would you like to use?",
                                       options=de_list,
                                       flags=flags_list)
            if desktop_env == "cli":
                print_warning("Warning: No desktop environment will be installed!")
                if verbose_kernel:
                    print_error("High verbosity kernel messages will print to TTY making it practically unusable.")
                print_header("If you plan to install an unsupported desktop environment, make sure to specify it "
                             "in /etc/eupnea.json after installation. Consider making a pr with support for this DE.")
                user_selection = ia_selection("Are you sure you want to continue?", options=["No", "Yes"], )
                if user_selection == "No":
                    print_status("No desktop will be installed.")
                    continue

            output_dict["de_name"] = desktop_env.lower()
            break
        print(f"{desktop_env} selected")
    elif output_dict["distro_name"] == "pop-os":
        output_dict["de_name"] = "cosmic-gnome"

    shell_list = ["bash", "fish", "zsh"]
    shell_flags_list = ["(recommended)", "", ""]
    while True:
        output_dict["shell"] = ia_selection("Which shell would you like to use?",
                                            options=shell_list,
                                            flags=shell_flags_list)
        break

    print_question("Enter a username for the new user")
    while True:
        output_dict["username"] = input("\033[94m" + "Username (default: 'localuser'): " + "\033[0m")
        if output_dict["username"] == "":
            print("Using 'localuser' as username")
            output_dict["username"] = "localuser"
            break
        found_invalid_char = False
        for char in output_dict["username"]:
            if char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-":
                print_warning(f"Username contains invalid character: {char}")
                found_invalid_char = True
                break
        if not found_invalid_char:
            print(f"Using {output_dict['username']} as username")
            break

    print_question("Please set a secure password")
    while True:
        passwd_temp = getpass("\033[94m" + "Password: " + "\033[0m")
        if passwd_temp == "":
            print_warning("Password cannot be empty")
            continue

        else:
            passwd_temp_repeat = getpass("\033[94m" + "Repeat password: " + "\033[0m")
            if passwd_temp == passwd_temp_repeat:
                output_dict["password"] = passwd_temp
                print("Password set")
                break
            else:
                print_warning("Passwords do not match, please try again")
                continue

    while True:
        kernel_type = ia_selection("Which kernel type would you like to use? Usually there is no need to change this. \nYou can change kernels in the future by using your package manager (eupnea-kernelname-kernel).",
                                   options=["ChromeOS", "Mainline"],
                                   flags=["(default, recommended for older devices)", "(newer kernel, recommended)"])

        output_dict["kernel_type"] = kernel_type.lower()
        break
    print(f"{kernel_type} kernel selected")

    # Check if usb reading is possible
    if not path_exists("/sys/dev/block"):
        print_warning("Couldn't read usb devices. Building image file.")
        skip_device = True

    if not skip_device:
        print_status("Available devices: ")
        usb_array = []
        usb_info_array = []
        lsblk_out = bash("lsblk -nd -o NAME,MODEL,SIZE,TRAN").splitlines()
        for line in lsblk_out:
            if line.find("usb") != -1 and line.find("0B") == -1:  # Print USB devices only with storage more than 0B
                usb_array.append(line[:3])
                usb_info_array.append(line[3:])
        if not usb_array:
            print_status("No available USBs/SD-cards found. Building image file.")
        else:
            device = ia_selection("Select USB-drive/SD-card name or 'image' to build an image",
                                  options=usb_array + ["image"],
                                  flags=usb_info_array + ["Build image instead of writing to USB/SD-card directly"])
            if device == "image":
                print("Building image instead of writing directly")
            else:
                print(f"Writing directly to {device}")
                output_dict["device"] = device

    print_status("User input complete")
    return output_dict


class KeyGetter:
    def arm(self):
        self.old_term = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin)

        atexit.register(self.disarm)

    def disarm(self):
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_term)

    def getch(self):
        self.arm()
        ch = sys.stdin.read(1)[0]
        self.disarm()
        return ch


def ia_selection(question: str, options: list = None, flags: list = None) -> str:
    print_question(question)
    return _draw_ia_selection(options, flags)


def _draw_ia_selection(options: list, flags: list = None):
    __UNPOINTED = " "
    __POINTED = ">"
    __INDEX = 0
    __LENGTH = len(options)
    __ARROWS = __UP, _ = 65, 66
    __ENTER = 10

    if flags is None:
        flags = []

    def _choices_print():
        for i, (option, flag) in enumerate(zip_longest(options, flags, fillvalue='')):
            if i == __INDEX:
                print(f" {__POINTED} {{0}}{option} {flag}{{1}}".format('\033[94m', '\033[0m'))
            else:
                print(f" {__UNPOINTED} {option} {flag}")

    def _choices_clear():
        print(f"\033[{__LENGTH}A\033[J", end='')

    def _move_pointer(ch_ord: int):
        nonlocal __INDEX
        __INDEX = max(0, __INDEX - 1) if ch_ord == __UP else min(__INDEX + 1, __LENGTH - 1)

    def _main_loop():
        kg = KeyGetter()
        _choices_print()
        while True:
            key = ord(kg.getch())
            if key in __ARROWS:
                _move_pointer(key)
            _choices_clear()
            _choices_print()
            if key == __ENTER:
                _choices_clear()
                _choices_print()
                break

    _main_loop()
    return options[__INDEX]
