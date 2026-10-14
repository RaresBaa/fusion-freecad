{
  description = "Fusion FreeCAD: a Fusion 360-style workflow and an MCP server for FreeCAD";

  # Add-ons pinned to the commits in addons.json (tested with FreeCAD 1.1.4).
  # Input names are the add-on names with "." replaced by "-".
  # mcp-server/tests/test_manifest.py checks these stay in sync with addons.json.
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    SearchBar = { url = "github:APEbbers/SearchBar/c36a2ed17e2ba5572fb0af19c5c560084f42296a"; flake = false; };
    fasteners = { url = "github:shaise/FreeCAD_FastenersWB/fddd07af422b7d3a69098b32333711c5eeae184c"; flake = false; };
    sheetmetal = { url = "github:shaise/FreeCAD_SheetMetal/ca922534bc192e114014e49ca3192a66cd77107c"; flake = false; };
    freecad-gears = { url = "github:looooo/freecad.gears/83ec154b1925347622b61812f75d2ed51e956b9f"; flake = false; };
    QuickMeasure = { url = "github:DanMiel/QuickMeasure/ebbd4b2d7dd7f40ed7b30a30a14b4221400cd1e8"; flake = false; };
    ThreadProfile = { url = "github:mwganson/ThreadProfile/2aa2e739c0f401d3addd28fd172d9f74c304aabc"; flake = false; };
    FusedFilamentDesign = { url = "github:rahix/FusedFilamentDesign/870e5dbb6bf8d276b54f053ca95456836803796d"; flake = false; };
    Gridfinity = { url = "github:Stu142/FreeCAD-Gridfinity-Workbench/6caeb02812bf3b389110c205c6fd48638353e957"; flake = false; };
    OpenTheme = { url = "github:obelisk79/OpenTheme/de8a3a86ae6779993f07318557c18e7adf221dde"; flake = false; };
    Curves = { url = "github:tomate44/CurvesWB/c08e21ba16b8d6c6846cee3c9a6b1ea950987f36"; flake = false; };
    Defeaturing = { url = "github:easyw/Defeaturing_WB/460cfdd02bddc622443b3dc78cc3ed2d31ccf0bd"; flake = false; };
    Manipulator = { url = "github:easyw/Manipulator/6d8990469d1c1c2788c873af96ebecff2377833d"; flake = false; };
    Render = { url = "github:FreeCAD/FreeCAD-render/08be2fe94b8a998323c8a5443f7f0afd0d05bed5"; flake = false; };
    FreeCAD-Ribbon = { url = "github:APEbbers/FreeCAD-Ribbon/3416a8a2e29763e3c3178cf09044e16aa94347c2"; flake = false; };
    PieMenu = { url = "github:Grubuntu/PieMenu/e95beb9ca7cb89cdd803b1e1e6aff222d87e11a8"; flake = false; };
  };

  outputs = { self, nixpkgs, ... }@inputs:
    let
      lib = nixpkgs.lib;
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      manifest = builtins.fromJSON (builtins.readFile ./addons.json);
      inputName = name: builtins.replaceStrings [ "." ] [ "-" ] name;

      # Add-on sets, like the install scripts' --addons option.
      setsFor = choice: {
        none = [ ];
        minimal = [ "required" ];
        default = [ "required" "recommended" ];
        all = [ "required" "recommended" "ui" ];
      }.${choice};
      addonsFor = choice:
        builtins.filter (a: builtins.elem a.set (setsFor choice)) manifest.addons;

      # The Fusion FreeCAD addon folder (its name in Mod/ must stay FusionFreeCAD).
      fusionAddon = ./addon/FusionFreeCAD;

      # { "<Mod folder name>" = <path>; } for our addon plus the chosen add-ons.
      modsFor = choice:
        { FusionFreeCAD = fusionAddon; }
        // lib.listToAttrs (map (a: lib.nameValuePair a.name inputs.${inputName a.name})
          (addonsFor choice));

      pythonPackagesFor = choice: lib.unique (lib.concatMap (a: a.python) (addonsFor choice));

      mkPackages = pkgs:
        let
          python = pkgs.python3;

          mcp-server = python.pkgs.buildPythonApplication {
            pname = "fusion-freecad-mcp";
            version = "0.1.0";
            pyproject = true;
            src = ./mcp-server;
            build-system = [ python.pkgs.hatchling ];
            dependencies = [ python.pkgs.mcp ];
            # The tests drive a real FreeCAD through the bridge.
            doCheck = false;
            pythonImportsCheck = [ "fusion_freecad_mcp" ];
            meta.mainProgram = "fusion-freecad-mcp";
          };

          # All Mod folders in one directory, e.g. for FreeCAD's --module-path.
          modsDir = choice: pkgs.linkFarm "fusion-freecad-mods-${choice}"
            (lib.mapAttrsToList (name: path: { inherit name path; }) (modsFor choice));

          # FreeCAD with the addons built in, via nixpkgs' freecad.customize.
          freecadWith = choice:
            pkgs.freecad.customize {
              name = "freecad-fusion";
              modules = lib.attrValues (modsFor choice);
              pythons = [ (ps: map (n: ps.${n}) (pythonPackagesFor choice)) ];
            };
        in
        {
          inherit mcp-server;
          mods = modsDir "default";
          mods-all = modsDir "all";
          default = mcp-server;
        }
        // lib.optionalAttrs (pkgs.freecad ? customize) {
          freecad = freecadWith "default";
          freecad-all = freecadWith "all";
        };
    in
    {
      packages = forAllSystems mkPackages;

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = lib.getExe self.packages.${pkgs.stdenv.hostPlatform.system}.mcp-server;
        };
      });

      # Home Manager: links the add-ons into FreeCAD's user Mod folder and installs
      # the MCP server. Works with any FreeCAD package.
      homeManagerModules.default = { config, pkgs, ... }:
        let
          cfg = config.programs.fusion-freecad;
          packages = self.packages.${pkgs.stdenv.hostPlatform.system};
        in
        {
          options.programs.fusion-freecad = {
            enable = lib.mkEnableOption "Fusion FreeCAD (Fusion-style workbench and MCP bridge)";
            addons = lib.mkOption {
              type = lib.types.enum [ "none" "minimal" "default" "all" ];
              default = "default";
              description = ''
                Add-ons to install with it: minimal = required ones, default = also the
                recommended ones, all = also FreeCAD Ribbon and PieMenu (these change the
                whole interface).
              '';
            };
            freecadDataDir = lib.mkOption {
              type = lib.types.str;
              default = "FreeCAD/v1-1";
              description = ''
                FreeCAD's user data folder under $XDG_DATA_HOME. FreeCAD 1.1 uses
                FreeCAD/v1-1; change it when a new FreeCAD version moves it.
              '';
            };
            linkFusionAddon = lib.mkOption {
              type = lib.types.bool;
              default = true;
              description = ''
                Link Fusion FreeCAD itself into the Mod folder. Turn off when developing
                it from a checkout (link that with scripts/install-addon.sh --addons none).
              '';
            };
            installFreeCAD = lib.mkOption {
              type = lib.types.bool;
              default = true;
              description = "Also install FreeCAD with the add-ons' Python packages.";
            };
            mcpServer = lib.mkOption {
              type = lib.types.bool;
              default = true;
              description = "Install the fusion-freecad-mcp command for AI agents.";
            };
          };

          config = lib.mkIf cfg.enable {
            xdg.dataFile = lib.mapAttrs'
              (name: path: lib.nameValuePair "${cfg.freecadDataDir}/Mod/${name}" { source = path; })
              (removeAttrs (modsFor cfg.addons)
                (lib.optional (!cfg.linkFusionAddon) "FusionFreeCAD"));

            home.packages =
              lib.optional cfg.mcpServer packages.mcp-server
              ++ lib.optional cfg.installFreeCAD
                (if pkgs.freecad ? customize then
                  # Modules come from the Mod links above; only add Python packages.
                  pkgs.freecad.customize {
                    name = "freecad";
                    pythons = [ (ps: map (n: ps.${n}) (pythonPackagesFor cfg.addons)) ];
                  }
                else pkgs.freecad);
          };
        };

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = [ pkgs.uv pkgs.python3 pkgs.freecad pkgs.git ];
          # Use nixpkgs' Python; uv's downloaded interpreters don't run on NixOS.
          env.UV_PYTHON_DOWNLOADS = "never";
          env.UV_PYTHON = "${pkgs.python3}/bin/python3";
        };
      });
    };
}
