#!/bin/bash

# =============================================================================
# FIRECRACKER CUSTOM KERNEL AND ROOTFS CREATION GUIDE
# =============================================================================

# SECTION 1: CREATING A LINUX KERNEL IMAGE
# =============================================================================
# sudo apt update
# sudo apt install bison flex libssl-dev libelf-dev build-essential git -y
download_firecracker_config() {
    local arch=${1:-$(uname -m)}
    local kernel_version=${2:-"6.1"}
    local acpi_support=${3:-"yes"}
    
    # Normalize architecture
    case "$arch" in
        x86_64|amd64)
            arch="x86_64"
            ;;
        aarch64|arm64)
            arch="aarch64"
            ;;
        *)
            echo "Unsupported architecture: $arch"
            return 1
            ;;
    esac
    
    # Determine config filename
    local config_name=""
    if [ "$arch" = "x86_64" ] && [ "$kernel_version" = "5.10" ] && [ "$acpi_support" = "no" ]; then
        config_name="microvm-kernel-ci-x86_64-5.10-no-acpi.config"
    elif [ "$arch" = "x86_64" ] && [ "$kernel_version" = "5.10" ]; then
        config_name="microvm-kernel-ci-x86_64-5.10.config"
    elif [ "$arch" = "x86_64" ] && [ "$kernel_version" = "6.1" ]; then
        config_name="microvm-kernel-ci-x86_64-6.1.config"
    elif [ "$arch" = "aarch64" ] && [ "$kernel_version" = "5.10" ]; then
        config_name="microvm-kernel-ci-aarch64-5.10.config"
    elif [ "$arch" = "aarch64" ] && [ "$kernel_version" = "6.1" ]; then
        config_name="microvm-kernel-ci-aarch64-6.1.config"
    else
        echo "Unsupported combination: arch=$arch, kernel=$kernel_version, acpi=$acpi_support"
        return 1
    fi
    
    # Download the config
    local base_url="https://github.com/firecracker-microvm/firecracker/raw/main/resources/guest_configs"
    local config_url="$base_url/$config_name"
    
    echo "Downloading Firecracker kernel config..."
    echo "Architecture: $arch"
    echo "Kernel Version: $kernel_version"
    echo "Config: $config_name"
    echo "URL: $config_url"
    
    if curl -LO "$config_url"; then
        make olddefconfig

        echo "✅ Successfully downloaded: $config_name"
        # Rename to .config for kernel build
        mv "$config_name" .config
        
        echo "Renamed to .config for kernel build"
        return 0
    else
        echo "❌ Failed to download config"
        return 1
    fi
}
create_custom_kernel() {
    echo "=== Creating Custom Linux Kernel ==="
    
    # Step 1: Get Linux source code
    git clone https://github.com/torvalds/linux.git linux.git
    cd linux.git
    
    # local kernel_version="v4.20"
    # git checkout $kernel_version
    
    # Step 3: Configure kernel (copy recommended config or use menuconfig)
    # Copy appropriate config from Firecracker resources, or:
    # cp /path/to/recommended/.config ./
    # make menuconfig  # for interactive configuration
    

    download_firecracker_config "$(uname -m)" "6.1" "yes"

    # Step 4: Build kernel based on architecture
    local arch=$(uname -m)
    echo "Building kernel for architecture: $arch"
    
    if [ "$arch" = "x86_64" ]; then
        echo "Building uncompressed ELF kernel for x86_64..."

        make vmlinux  -j$(nproc) \
        KCFLAGS="-w -Wno-error" \
        HOSTCFLAGS="-w -Wno-error" \

        echo "Kernel image created at: ./vmlinux"
    elif [ "$arch" = "aarch64" ]; then
        echo "Building PE formatted kernel for aarch64..."
        make Image  -j$(nproc) \
        KCFLAGS="-w -Wno-error" \
        HOSTCFLAGS="-w -Wno-error" 


        echo "Kernel image created at: ./arch/arm64/boot/Image"
    else
        echo "Unsupported architecture: $arch"
        return 1
    fi
}

# Alternative method: Use Firecracker's provided build script
build_kernel_with_recipe() {
    local kernel_version=${1:-"6.1"}  # Default to 6.1
    
    echo "=== Building Kernel Using Firecracker Recipe ==="
    echo "Building kernel version: $kernel_version"
    
    # Build specific kernel version
    ./tools/devtool build_ci_artifacts kernels $kernel_version
    
    # Built kernels stored under resources/$(uname -m)
    echo "Built kernels available in: resources/$(uname -m)/"
}

# SECTION 2: CREATING A LINUX ROOTFS IMAGE
# =============================================================================

create_custom_rootfs() {
    local rootfs_size=${1:-50}  # Default 50MB
    local rootfs_name=${2:-"rootfs.ext4"}
    
    echo "=== Creating Custom Linux RootFS ==="
    echo "Creating $rootfs_size MB EXT4 rootfs: $rootfs_name"
    
    # Step 1: Create properly-sized file
    dd if=/dev/zero of=$rootfs_name bs=1M count=$rootfs_size
    
    # Step 2: Create empty filesystem
    mkfs.ext4 $rootfs_name
    
    # Step 3: Mount filesystem for population
    local mount_point="/tmp/my-rootfs"
    mkdir -p $mount_point
    sudo mount $rootfs_name $mount_point
    
    # Step 4: Populate with Alpine + OpenRC (simplified approach)
    echo "Populating rootfs with Alpine Linux..."
    
    # Use Docker to create Alpine-based rootfs
    docker run -it --rm -v $mount_point:/my-rootfs alpine /bin/sh -c "
        # Install required packages
        apk add --no-cache openrc util-linux
        
        # Configure init system
        ln -s agetty /etc/init.d/agetty.ttyS0
        echo ttyS0 > /etc/securetty
        rc-update add agetty.ttyS0 default
        
        # Add essential filesystem mounts
        rc-update add devfs boot
        rc-update add procfs boot
        rc-update add sysfs boot
        
        # Copy system files to rootfs
        for d in bin etc lib root sbin usr; do 
            tar c \"/\$d\" | tar x -C /my-rootfs
        done
        
        # Create essential directories
        for dir in dev proc run sys var; do 
            mkdir -p /my-rootfs/\$dir
        done
    "
    
    # Step 5: Unmount filesystem
    sudo umount $mount_point
    rmdir $mount_point
    
    echo "RootFS created successfully: $rootfs_name"
}

# Alternative method: Use Firecracker's provided build script
build_rootfs_with_recipe() {
    echo "=== Building RootFS Using Firecracker Recipe ==="
    echo "Building minimized Ubuntu 22.04 rootfs..."
    
    ./tools/devtool build_ci_artifacts rootfs
    
    echo "RootFS created: ubuntu-22.04.ext4"
}

# SECTION 3: CREATING FREEBSD KERNEL AND ROOTFS
# =============================================================================

create_freebsd_images() {
    echo "=== Creating FreeBSD Kernel and RootFS ==="
    echo "Requirements: FreeBSD 13+ system with ~50GB disk space"
    
    # This function should be run on a FreeBSD system
    if [ "$(uname -s)" != "FreeBSD" ]; then
        echo "Error: This must be run on a FreeBSD system"
        echo "Use FreeBSD 13+ (Firecracker support available since FreeBSD 14.0)"
        return 1
    fi
    
    # Step 1: Install git and get FreeBSD source
    pkg install -y git
    git clone https://git.freebsd.org/src.git /usr/src
    
    # Step 2: Build FreeBSD with Firecracker configuration
    echo "Building FreeBSD with FIRECRACKER kernel config..."
    make -C /usr/src buildworld buildkernel KERNCONF=FIRECRACKER
    
    # Step 3: Create Firecracker-specific release
    make -C /usr/src/release firecracker DESTDIR=$(pwd)
    
    echo "FreeBSD images created:"
    echo "  Kernel: freebsd-kern.bin"
    echo "  RootFS: freebsd-rootfs.bin"
}

# SECTION 4: UTILITY FUNCTIONS
# =============================================================================

# Verify kernel compatibility
verify_kernel() {
    local kernel_file=$1
    local arch=$(uname -m)
    
    echo "=== Verifying Kernel: $kernel_file ==="
    
    if [ ! -f "$kernel_file" ]; then
        echo "Error: Kernel file not found: $kernel_file"
        return 1
    fi
    
    if [ "$arch" = "x86_64" ]; then
        file_output=$(file "$kernel_file")
        if [[ "$file_output" == *"ELF"* ]] && [[ "$file_output" == *"not stripped"* ]]; then
            echo "✓ Kernel format: Valid uncompressed ELF"
        else
            echo "✗ Warning: Kernel may not be in correct format for Firecracker"
        fi
    elif [ "$arch" = "aarch64" ]; then
        echo "✓ For aarch64, ensure kernel is PE formatted"
    fi
}

# Display supported kernel versions
show_supported_kernels() {
    echo "=== Currently Supported Kernel Versions ==="
    echo "• 5.10 (with ACPI support)"
    echo "• 5.10-no-acpi (without ACPI support)"  
    echo "• 6.1"
    echo ""
    echo "Note: Check Firecracker's kernel support policy for the most current information"
}

# SECTION 5: MAIN EXECUTION FUNCTIONS
# =============================================================================

# Quick setup function
quick_setup() {
    echo "=== Quick Firecracker Setup ==="
    
    # Create both kernel and rootfs
    create_custom_kernel
    create_custom_rootfs 50 "firecracker-rootfs.ext4"
    
    echo "Setup complete! You can now use these with Firecracker:"
    echo "  Kernel: ./linux.git/vmlinux"
    echo "  RootFS: ./firecracker-rootfs.ext4"
}

# Help function
show_help() {
    echo "Firecracker Custom Image Creation Tool"
    echo ""
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  --kernel              Create custom Linux kernel"
    echo "  --kernel-version VER  Build specific kernel version using recipe"
    echo "  --rootfs [SIZE] [NAME] Create custom rootfs (default: 50MB, rootfs.ext4)"
    echo "  --rootfs-recipe       Build rootfs using Firecracker recipe"
    echo "  --freebsd             Create FreeBSD images (requires FreeBSD system)"
    echo "  --verify KERNEL       Verify kernel compatibility"
    echo "  --supported           Show supported kernel versions"
    echo "  --quick               Quick setup (kernel + rootfs)"
    echo "  --help                Show this help"
}

# Main execution
main() {
    case "$1" in
        --kernel)
            create_custom_kernel
            ;;
        --kernel-version)
            build_kernel_with_recipe "$2"
            ;;
        --rootfs)
            create_custom_rootfs "$2" "$3"
            ;;
        --rootfs-recipe)
            build_rootfs_with_recipe
            ;;
        --freebsd)
            create_freebsd_images
            ;;
        --verify)
            verify_kernel "$2"
            ;;
        --supported)
            show_supported_kernels
            ;;
        --quick)
            quick_setup
            ;;
        --help|*)
            show_help
            ;;
    esac
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi