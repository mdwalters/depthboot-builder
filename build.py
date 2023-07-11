#!/usr/bin/env python3
import argparse
import atexit
import json
import os
from typing import Tuple
from urllib.error import URLError

from functions import *

img_mnt = ""  # empty to avoid variable not defined error in exit_handler


# the exit handler with user messages is in main.py
def exit_handler():
    # Only trigger cleanup if the user initiated the exit, not if the script exited on its own
    exc_type = sys.exc_info()[0]
    if exc_type != KeyboardInterrupt:
        return
    print_error("Ctrl+C detected. Cleaning machine and exiting...")
    # Kill arch gpg agent if present
    print_status("Killing gpg-agent arch processes if they exist")
    gpg_pids = []
    for line in bash("ps aux").split("\n"):
        if "gpg-agent --homedir /etc/pacman.d/gnupg --use-standard-socket --daemon" in line:
            temp_string = line[line.find(" "):].strip()
            gpg_pids.append(temp_string[:temp_string.find(" ")])
    for pid in gpg_pids:
        print(f"Killing gpg-agent proces with pid: {pid}")
        bash(f"kill {pid}")

    print_status("Unmounting partitions")
    with contextlib.suppress(subprocess.CalledProcessError):
        bash("umount -lf /mnt/depthboot")  # umount mountpoint
    sleep(5)  # wait for umount to finish

    # unmount image/device completely from system
    # on crostini umount fails for some reason
    with contextlib.suppress(subprocess.CalledProcessError):
        bash(f"umount -lf {img_mnt}p*")  # umount all partitions from image
    with contextlib.suppress(subprocess.CalledProcessError):
        bash(f"umount -lf {img_mnt}*")  # umount all partitions from usb/sd-card


# download the distro rootfs
def download_rootfs(distro_name: str, distro_version: str) -> None:
    try:
        match distro_name:
            case "arch":
                print_status("Downloading latest arch rootfs from geo.mirror.pkgbuild.com")
                download_file("https://geo.mirror.pkgbuild.com/iso/latest/archlinux-bootstrap-x86_64.tar.gz",
                              "/tmp/depthboot-build/arch-rootfs.tar.gz")
            case "ubuntu" | "fedora":
                print_status(f"Downloading {distro_name} rootfs, version {distro_version} from eupnea github releases")
                download_file(f"https://github.com/eupnea-linux/{distro_name}-rootfs/releases/latest/download/"
                              f"{distro_name}-rootfs-{distro_version}.tar.xz",
                              f"/tmp/depthboot-build/{distro_name}-rootfs.tar.xz")
            case "pop-os":
                print_status("Downloading pop-os rootfs from eupnea github releases")
                download_file("https://github.com/eupnea-linux/pop-os-rootfs/releases/latest/download/pop-os-rootfs-"
                              "22.04.split.aa", "/tmp/depthboot-build/pop-os-rootfs.split.aa")
                # print_status("Downloading pop-os rootfs from eupnea GitHub releases, part 2/2")
                # download_file("https://github.com/eupnea-linux/pop-os-rootfs/releases/latest/download/pop-os-rootfs"
                #              "-22.04.split.ab", "/tmp/depthboot-build/pop-os-rootfs.split.ab")
                print_status("Combining split pop-os rootfs, might take a while")
                bash("cat /tmp/depthboot-build/pop-os-rootfs.split.?? > /tmp/depthboot-build/pop-os-rootfs.tar.xz")
    except URLError:
        print_error("Couldn't download rootfs. Check your internet connection and try again. If the error persists, "
                    "create an issue with the distro and version in the name")
        sys.exit(1)


# Create, mount, partition the img and flash the eupnea kernel
def prepare_img(img_size: int) -> bool:
    print_status("Preparing image")
    try:
        bash(f"fallocate -l {img_size}G depthboot.img")
    except subprocess.CalledProcessError:  # try fallocate, if it fails use dd
        bash(f"dd if=/dev/zero of=depthboot.img status=progress bs=1024 count={img_size * 1000000}")

    print_status("Mounting empty image")
    global img_mnt
    try:
        img_mnt = bash("losetup -f --show depthboot.img")
    except subprocess.CalledProcessError as e:
        if not bash("systemd-detect-virt").lower().__contains__("wsl"):  # if not running WSL, the error is unexpected
            raise e
        print_error("Losetup failed. Make sure you are using WSL version 2 aka WSL2.")
        sys.exit(1)
    if img_mnt == "":
        print_error("Failed to mount image")
        sys.exit(1)
    partition(False)
    return False


# Prepare USB/SD-card
def prepare_usb_sd(device: str) -> bool:
    print_status("Preparing USB/SD-card")

    # fix device name if needed
    if device.endswith("/") or device.endswith("1") or device.endswith("2"):
        device = device[:-1]
    # add /dev/ to device name, if needed
    if not device.startswith("/dev/"):
        device = f"/dev/{device}"

    global img_mnt
    img_mnt = device

    # unmount all partitions
    with contextlib.suppress(subprocess.CalledProcessError):
        bash(f"umount -lf {img_mnt}*")

    if img_mnt.__contains__("mmcblk"):  # sd card
        partition(write_usb=False)
        return False
    else:
        partition(write_usb=True)
        return True


def partition(write_usb: bool) -> None:
    print_status("Preparing device/image partition")

    # Determine rootfs part name
    rootfs_mnt = f"{img_mnt}3" if write_usb else f"{img_mnt}p3"
    # remove pre-existing partition table from storage device
    bash(f"wipefs -af {img_mnt}")

    # format as per depthcharge requirements,
    # READ: https://wiki.gentoo.org/wiki/Creating_bootable_media_for_depthcharge_based_devices
    try:
        bash(f"parted -s {img_mnt} mklabel gpt")
    # TODO: Only show this prompt when parted throws: "we have been unable to inform the kernel of the change"
    # TODO: Check if partprob-ing the drive could fix this error
    except subprocess.CalledProcessError:
        print_error("Failed to create partition table. Try physically unplugging and replugging the USB/SD-card.")
        print_question("If you chose the image option or are seeing this message the second time, create an issue on "
                       "GitHub/Discord/Revolt")
        sys.exit(1)
    bash(f"parted -s -a optimal {img_mnt} unit mib mkpart Kernel 1 65")  # kernel partition
    bash(f"parted -s -a optimal {img_mnt} unit mib mkpart Kernel 65 129")  # reserve kernel partition
    bash(f"parted -s -a optimal {img_mnt} unit mib mkpart Root 129 100%")  # rootfs partition
    bash(f"cgpt add -i 1 -t kernel -S 1 -T 5 -P 15 {img_mnt}")  # set kernel flags
    bash(f"cgpt add -i 2 -t kernel -S 1 -T 5 -P 1 {img_mnt}")  # set backup kernel flags

    print_status("Formatting rootfs partition")
    # Create rootfs ext4 partition
    bash(f"yes 2>/dev/null | mkfs.ext4 {rootfs_mnt}")  # 2>/dev/null is to supress yes broken pipe warning

    # Mount rootfs partition
    bash(f"mount {rootfs_mnt} /mnt/depthboot")

    print_status("Device/image preparation complete")


# extract the rootfs to /mnt/depthboot
def extract_rootfs(distro_name: str, distro_version: str) -> None:
    print_status("Extracting rootfs")
    match distro_name:
        case "arch":
            print_status("Extracting arch rootfs")
            mkdir("/tmp/depthboot-build/arch-rootfs")
            extract_file("/tmp/depthboot-build/arch-rootfs.tar.gz", "/tmp/depthboot-build/arch-rootfs")
            cpdir("/tmp/depthboot-build/arch-rootfs/root.x86_64/", "/mnt/depthboot/")
        case "pop-os" | "ubuntu" | "fedora":
            print_status(f"Extracting {distro_name} rootfs")
            extract_file(f"/tmp/depthboot-build/{distro_name}-rootfs.tar.xz", "/mnt/depthboot")
        case "generic":
            def prompt_user_for_rootfs():
                while True:
                    # use read for path autocompletion
                    user_rootfs_path = input("\033[92m" + "Please manually extract the rootfs and provide the path "
                                                          "to the root directory:\n" + "\033[0m")
                    if user_rootfs_path.endswith("/"):
                        user_rootfs_path = user_rootfs_path[:-1]
                    # we could check for more dirs but this should be enough
                    if not path_exists(f"{user_rootfs_path}/usr") or not path_exists(f"{user_rootfs_path}/bin"):
                        print_error("Path does not contain a rootfs. Verify that you are entering the full path, "
                                    "without any shortcuts (i.e. ~ for home, ./ for current dir, etc...)")
                        continue
                    return user_rootfs_path

            print_status("Starting generic rootfs extraction")
            # ask user for path to iso
            while True:
                print_warning(
                    "You will need a full iso of the distro. Netboot, pure initrd, etc... images will not work.")
                # user read for path autocompletion
                iso_path = input("\033[92m" + "Enter full path to the ISO file:\n" + "\033[0m")
                if not path_exists(iso_path) or not iso_path.endswith(".iso"):
                    print_error("File does not exist or is not an iso file. Verify that you are entering the full path,"
                                " without any shortcuts (i.e. ~ for home, etc)")
                    continue
                break
            # Check if running under crostini
            try:
                with open("/sys/devices/virtual/dmi/id/product_name", "r") as file:
                    product_name = file.read().strip()
            except FileNotFoundError:
                product_name = ""  # wsl doesn't have dmi info
            if product_name == "crosvm":
                print_error("Crostini doesn't support mounting iso files.")
                prompt_user_for_rootfs()
            # mount iso
            print_status("Mounting iso")
            iso_loop_dev = bash(f"losetup -fP --show {iso_path}")
            mkdir("/tmp/depthboot-build/iso-mount")
            # find the biggest partition
            partitions_json = json.loads(bash(f"lsblk -nbJ {iso_loop_dev} -o SIZE"))["blockdevices"]
            # remove first device as it's the total size
            partitions_json.pop(0)
            # find the index of the biggest partition
            max_index = partitions_json.index(max(partitions_json, key=lambda x: x['size'])) + 1
            print_status(f"Mounting biggest partition at {iso_loop_dev}p{max_index}")
            bash(f"mount {iso_loop_dev}p{max_index} /tmp/depthboot-build/iso-mount -o ro")
            # search for rootfs
            print_status("Searching for squashfs")
            file_path = ""
            for dirpath, dirnames, filenames in os.walk("/tmp/depthboot-build/iso-mount"):
                if "squashfs.img" in filenames:
                    file_path = os.path.join(dirpath, "squashfs.img")
                    print(f"Found squashfs.img at {file_path}")
                    break
                elif "filesystem.squashfs" in filenames:
                    file_path = os.path.join(dirpath, "filesystem.squashfs")
                    print(f"Found filesystem.squashfs at {file_path}")
                    break
                elif "rootfs.sfs" in filenames:
                    file_path = os.path.join(dirpath, "rootfs.sfs")
                    print(f"Found rootfs.sfs at {file_path}")
                    break
                elif "image.squashfs" in filenames:
                    file_path = os.path.join(dirpath, "image.squashfs")
                    print(f"Found image.squashfs at {file_path}")
                    break
            if not file_path:
                print_error("Could not find squashfs in iso")
                cpdir(prompt_user_for_rootfs(), "/mnt/depthboot")
            else:
                # extract rootfs
                print_status("Extracting squashfs")
                mkdir("/tmp/depthboot-build/squashfs-extract")
                # use os.system to show progress immediately
                os.system(f"unsquashfs -d /tmp/depthboot-build/squashfs-extract {file_path}")

                # check if a real rootfs was extracted or an img file
                if path_exists("/tmp/depthboot-build/squashfs-extract/usr") and path_exists(
                        "/tmp/depthboot-build/squashfs-extract/bin"):
                    print_status("Found rootfs in squashfs, copying to image/device")
                    cpdir("/tmp/depthboot-build/squashfs-extract/", "/mnt/depthboot")
                else:
                    # find img file
                    print_status("Searching for img file in extracted squashfs")
                    img_file_path = ""
                    for dirpath, dirnames, filenames in os.walk("/tmp/depthboot-build/squashfs-extract"):
                        for file in filenames:
                            if file.endswith(".img"):
                                img_file_path = os.path.join(dirpath, file)
                                print(f"Found rootfs img at {img_file_path}")
                                break
                    if not img_file_path:
                        print_error("Could not find rootfs img in squashfs")
                        cpdir(prompt_user_for_rootfs(), "/mnt/depthboot")
                    else:
                        # mount img file
                        print_status("Mounting img file")
                        img_loop_dev = bash(f"losetup -fP --show {img_file_path}")
                        mkdir("/tmp/depthboot-build/img-mount")
                        bash(f"mount {img_loop_dev} /tmp/depthboot-build/img-mount -o ro")
                        # search for rootfs
                        print_status("Searching for rootfs inside img")
                        img_rootfs_path = ""
                        for dirpath, dirnames, filenames in os.walk("/tmp/depthboot-build/img-mount"):
                            if "usr" in dirnames and "bin" in dirnames:
                                img_rootfs_path = dirpath
                                print(f"Found rootfs at {img_rootfs_path}")
                                break
                        if not img_rootfs_path:
                            print_error("Could not find rootfs inside img")
                            cpdir(prompt_user_for_rootfs(), "/mnt/depthboot")
                        else:
                            cpdir(img_rootfs_path, "/mnt/depthboot")

    print_status("\n" + "Rootfs extraction complete")


# Configure distro agnostic options
def post_extract(build_options) -> None:
    print_status("Applying distro agnostic configuration")
    if build_options["distro_name"] != "generic":
        # Create a temporary resolv.conf for internet inside the chroot
        mkdir("/mnt/depthboot/run/systemd/resolve", create_parents=True)  # dir doesnt exist coz systemd didnt run
        open("/mnt/depthboot/run/systemd/resolve/stub-resolv.conf", "w").close()  # create empty file for mount
        # Bind mount host resolv.conf to chroot resolv.conf.
        # If chroot /etc/resolv.conf is a symlink, then it will be resolved to the real file and bind mounted
        # This is needed for internet inside the chroot
        bash("mount --bind /etc/resolv.conf /mnt/depthboot/etc/resolv.conf")

        # the following mounts are mostly unneeded, but will produce a lot of warnings if not mounted
        # even though the resulting image will work as intended and won't have any issues
        # mounting the full directories results in broken host systems -> only mount what's explicitly needed

        # systemd needs /proc to not throw warnings
        bash("mount --types proc /proc /mnt/depthboot/proc")

        # pacman needs the /dev/fd to not throw warnings
        # check if link already exists, if not, create it
        if not path_exists("/mnt/depthboot/dev/fd"):
            bash("cd /mnt/depthboot && ln -s /proc/self/fd ./dev/fd")

        # create new /dev/pts for apt to be able to write logs and not throw warnings
        mkdir("/mnt/depthboot/dev/pts", create_parents=True)
        bash("mount --types devpts devpts /mnt/depthboot/dev/pts")

        # create depthboot settings file for postinstall scripts to read
        with open("configs/eupnea.json", "r") as settings_file:
            settings = json.load(settings_file)
        settings["distro_name"] = build_options["distro_name"]
        settings["distro_version"] = build_options["distro_version"]
        settings["de_name"] = build_options["de_name"]
        settings["shell"] = build_options["shell"]
        if build_options["device"] != "image":
            settings["install_type"] = "direct"
        with open("/mnt/depthboot/etc/eupnea.json", "w") as settings_file:
            json.dump(settings, settings_file)

        print_status("Fixing screen rotation")
        # Install hwdb file to fix auto rotate being flipped on some devices
        cpfile("configs/hwdb/61-sensor.hwdb", "/mnt/depthboot/etc/udev/hwdb.d/61-sensor.hwdb")
        chroot("systemd-hwdb update")

        print_status("Cleaning /boot")
        rmdir("/mnt/depthboot/boot")  # clean stock kernels from /boot

    if build_options["distro_name"] == "fedora":
        print_status("Enabling resolved.conf systemd service")
        # systemd-resolved.service needed to create /etc/resolv.conf link. Not enabled by default on fedora
        # on other distros networkmanager takes care of this
        chroot("systemctl enable systemd-resolved")

    print_status("Configuring user")
    username = build_options["username"]  # quotes interfere with functions below
    chroot(f"useradd --create-home --shell /bin/{build_options['shell']} {username}")
    password = build_options["password"]  # quotes interfere with functions below
    chroot(f"echo '{username}:{password}' | chpasswd")
    with open("/mnt/depthboot/etc/group", "r") as group_file:
        group_lines = group_file.readlines()
    for line in group_lines:
        match line.split(":")[0]:
            case "sudo":
                chroot(f"usermod -aG sudo {username}")
            case "wheel":
                chroot(f"usermod -aG wheel {username}")
            case "doas":
                chroot(f"usermod -aG doas {username}")

    # set timezone build system timezone on device
    # In some environments(Crouton), the timezone is not set -> ignore in that case
    with contextlib.suppress(subprocess.CalledProcessError):
        host_time_zone = bash("file /etc/localtime")  # read host timezone link
        host_time_zone = host_time_zone[host_time_zone.find("/usr/share/zoneinfo/"):].strip()  # get actual timezone
        chroot(f"ln -sf {host_time_zone} /etc/localtime")

    print_status("Distro agnostic configuration complete")


# post extract and distro config
def post_config(distro_name: str, verbose_kernel: bool, kernel_type: str, is_usb,
                local_path: str) -> None:
    if distro_name != "generic":
        # Enable postinstall service
        print_status("Enabling postinstall service")
        chroot("systemctl enable eupnea-postinstall.service")

    # if local path option was used, extract modules and headers to the rootfs
    # check if at least kernel image and modules exist as otherwise the kernel won't boot
    if path_exists(f"{local_path}modules.tar.xz") and path_exists(f"{local_path}bzImage"):
        print_status("Extracting kernel modules from local path to rootfs")
        extract_file(f"{local_path}modules.tar.xz", "/mnt/depthboot/lib/modules/")
        kernel_path = f"{local_path}bzImage"  # set kernel path to local path
        if path_exists(f"{local_path}headers.tar.xz"):  # kernel headers are not required to boot
            print_status("Extracting kernel headers from local path")
            extract_file(f"{local_path}headers.tar.xz", "/mnt/depthboot/usr/src/")
    else:
        kernel_path = f"/mnt/depthboot/boot/vmlinuz-eupnea-{kernel_type}"

    # flash kernel
    # get uuid of rootfs partition
    rootfs_mnt = f"{img_mnt}3" if is_usb else f"{img_mnt}p3"
    rootfs_partuuid = bash(f"blkid -o value -s PARTUUID {rootfs_mnt}")
    print_status(f"Rootfs partition UUID: {rootfs_partuuid}")

    # write PARTUUID to kernel flags and save it as a file
    base_string = "console= root=PARTUUID=insert_partuuid i915.modeset=1 rootwait rw fbcon=logo-pos:center,logo-count:1"
    if distro_name in {"pop-os", "ubuntu"}:
        base_string += ' security=apparmor'
    if distro_name == 'fedora':
        base_string += ' security=selinux'
    if verbose_kernel:
        base_string = base_string.replace("console=", "loglevel=15")
    with open("kernel.flags", "w") as config:
        config.write(base_string.replace("insert_partuuid", rootfs_partuuid))

    print_status("Flashing kernel to device/image")
    # Sign kernel
    bash("futility vbutil_kernel --arch x86_64 --version 1 --keyblock /usr/share/vboot/devkeys/kernel.keyblock "
         "--signprivate /usr/share/vboot/devkeys/kernel_data_key.vbprivk --bootloader kernel.flags "
         f"--config kernel.flags --vmlinuz {kernel_path} --pack /tmp/depthboot-build/bzImage.signed")

    # Flash kernel
    if is_usb:
        # if writing to usb, then no p in partition name
        bash(f"dd if=/tmp/depthboot-build/bzImage.signed of={img_mnt}1")
        bash(f"dd if=/tmp/depthboot-build/bzImage.signed of={img_mnt}2")  # Backup kernel
    else:
        # image is a loop device -> needs p in part name
        bash(f"dd if=/tmp/depthboot-build/bzImage.signed of={img_mnt}p1")
        bash(f"dd if=/tmp/depthboot-build/bzImage.signed of={img_mnt}p2")  # Backup kernel

    # Fedora requires all files to be relabled for SELinux to work
    # If this is not done, SELinux will prevent users from logging in
    if distro_name == "fedora":
        print_status("Relabeling files for SELinux")

        # The following script needs some specific files in /proc -> unmount /proc
        bash("umount -lR /mnt/depthboot/proc")

        # copy /proc files needed for fixfiles
        mkdir("/mnt/depthboot/proc/self")
        cpfile("configs/selinux/mounts", "/mnt/depthboot/proc/self/mounts")
        cpfile("configs/selinux/mountinfo", "/mnt/depthboot/proc/self/mountinfo")

        # copy /sys files needed for fixfiles
        mkdir("/mnt/depthboot/sys/fs/selinux/initial_contexts/", create_parents=True)
        cpfile("configs/selinux/unlabeled", "/mnt/depthboot/sys/fs/selinux/initial_contexts/unlabeled")

        # Backup original selinux
        cpfile("/mnt/depthboot/usr/sbin/fixfiles", "/mnt/depthboot/usr/sbin/fixfiles.bak")
        # Copy patched fixfiles script
        cpfile("configs/selinux/fixfiles", "/mnt/depthboot/usr/sbin/fixfiles")

        chroot("/sbin/fixfiles -T 0 restore")

        # Restore original fixfiles
        cpfile("/mnt/depthboot/usr/sbin/fixfiles.bak", "/mnt/depthboot/usr/sbin/fixfiles")
        rmfile("/mnt/depthboot/usr/sbin/fixfiles.bak")

    # Unmount everything
    with contextlib.suppress(subprocess.CalledProcessError):  # will throw errors for unmounted paths
        bash("umount -lR /mnt/depthboot")  # recursive unmount

    # Clean all temporary files from image/sd-card to reduce its size
    rmdir("/mnt/depthboot/tmp")
    rmdir("/mnt/depthboot/var/tmp")
    rmdir("/mnt/depthboot/var/cache")
    rmdir("/mnt/depthboot/proc")
    rmdir("/mnt/depthboot/run")
    rmdir("/mnt/depthboot/sys")
    rmdir("/mnt/depthboot/lost+found")
    rmdir("/mnt/depthboot/dev")


# the main build function
def start_build(build_options: dict, args: argparse.Namespace) -> None:
    if args.verbose:
        print(args)
    set_verbose(args.verbose)
    atexit.register(exit_handler)
    print_status("Starting build")

    print_status("Creating temporary build directory + mount point")
    mkdir("/tmp/depthboot-build", create_parents=True)
    mkdir("/mnt/depthboot", create_parents=True)

    local_path_posix = ""
    if args.local_path is None:  # default
        download_rootfs(build_options["distro_name"], build_options["distro_version"])
    else:  # if local path is specified, copy files from it, instead of downloading from the internet
        print_status("Copying local files to /tmp/depthboot-build")
        # clean local path string
        local_path_posix = args.local_path if args.local_path.endswith("/") else f"{args.local_path}/"

        # copy distro rootfs
        try:
            cpfile(f"{local_path_posix}rootfs.tar.xz",
                   f"/tmp/depthboot-build/{build_options['distro_name']}-rootfs.tar.xz")
        except FileNotFoundError:
            print_warning(f"File 'rootfs.tar.xz' not found in {args.local_path}. Attempting to download rootfs")
            download_rootfs(build_options["distro_name"], build_options["distro_version"])

    # Setup device
    if build_options["device"] == "image":
        is_usb = prepare_img(args.image_size[0])
    else:
        is_usb = prepare_usb_sd(build_options["device"])
    # Extract rootfs and configure distro agnostic settings
    extract_rootfs(build_options["distro_name"], build_options["distro_version"])
    post_extract(build_options)

    match build_options["distro_name"]:
        case "ubuntu":
            import distro.ubuntu as distro
        case "arch":
            import distro.arch as distro
        case "fedora":
            import distro.fedora as distro
        case "pop-os":
            import distro.pop_os as distro
        case _:
            print_status("Generic install, skipping distro specific configuration")
    with contextlib.suppress(UnboundLocalError):
        distro.config(build_options["de_name"], build_options["distro_version"], args.verbose,
                      build_options["kernel_type"], build_options["shell"])

    post_config(build_options["distro_name"], args.verbose_kernel, build_options["kernel_type"], is_usb,
                local_path_posix)

    print_status("Unmounting image/device")

    bash("sync")  # write all pending changes to usb

    # unmount image/device completely from system
    # on crostini umount fails for some reason
    with contextlib.suppress(subprocess.CalledProcessError):
        bash(f"umount -lR {img_mnt}p*")  # umount all partitions from image
    with contextlib.suppress(subprocess.CalledProcessError):
        bash(f"umount -lR {img_mnt}*")  # umount all partitions from usb/sd-card

    # unmount any isos/images from /tmp/depthboot-build
    with contextlib.suppress(subprocess.CalledProcessError):
        bash("umount -lR /tmp/depthboot-build/*")

    # inform users about existence of system installers on the iso files
    if build_options["distro_name"] == "generic":
        print_header("Generic ISOs usually include a system installer. Do not use it, as it will try to install the "
                     "distro in a traditional way. Instead, use 'install-to-internal' from the eupnea-utils repo if you"
                     " wish to install your distro to the internal disk.")
        input("\033[92m" + "Press Enter to continue" + "\033[0m")

    if build_options["device"] == "image":
        try:
            with open("/sys/devices/virtual/dmi/id/product_name", "r") as file:
                product_name = file.read().strip()
        except FileNotFoundError:  # WSL doesnt have dmi data
            product_name = ""
        # TODO: Fix shrinking on Crostini
        if product_name != "crosvm" and not args.no_shrink:
            # Shrink image to actual size
            print_status("Shrinking image")
            bash(f"e2fsck -fpv {img_mnt}p3")  # Force check filesystem for errors
            bash(f"resize2fs -f -M {img_mnt}p3")
            block_count = int(bash(f"dumpe2fs -h {img_mnt}p3 | grep 'Block count:'")[12:].split()[0])
            actual_fs_in_bytes = block_count * 4096
            # the kernel part is always the same size -> sector amount: 131072 * 512 => 67108864 bytes
            # There are 2 kernel partitions -> 67108864 bytes * 2 = 134217728 bytes
            actual_fs_in_bytes += 134217728
            actual_fs_in_bytes += 20971520  # add 20mb for linux to be able to boot properly
            bash(f"truncate --size={actual_fs_in_bytes} ./depthboot.img")
        if product_name == "crosvm":
            # rename the image to .bin for the chromeos recovery utility to be able to flash it
            bash("mv ./depthboot.img ./depthboot.bin")

        bash(f"losetup -d {img_mnt}")  # unmount image from loop device
        print_header(f"The ready-to-boot {build_options['distro_name'].capitalize()} Depthboot image is located at "
                     f"{get_full_path('.')}/depthboot.img")
    else:
        print_header(f"USB/SD-card is ready to boot {build_options['distro_name'].capitalize()}")
        print_header("It is safe to remove the USB-drive/SD-card now.")
    print_header("Please report any bugs/issues on GitHub or on the Discord server.")


if __name__ == "__main__":
    print_error("Do not run this file directly. Instead, run main.py")
