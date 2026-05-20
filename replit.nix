{pkgs}: {
  deps = [
    pkgs.glib
    pkgs.libGL
    pkgs.xorg.libXrender
    pkgs.xorg.libXext
    pkgs.xorg.libX11
    pkgs.xorg.libxcb
  ];
}
