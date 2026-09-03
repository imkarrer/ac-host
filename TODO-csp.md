# Custom Shaders Patch (done)

Players install CSP from [acstuff.club/patch](https://acstuff.club/patch/) (0.2.11). Required for:

- [Toyota GR86 Premium](https://www.assettoworld.com/car/toyota-gr86-premium) (`tbb_toyota_gr86_premium`)
- [Honda Civic Type-R FK8](https://www.assettoworld.com/car/honda-civic-type-r-fk8-5) (`pc_civic`)

Joiners install CSP via Content Manager before they join. Folder names are ACD keys — do not rename.

Do not patch kn5/`data.acd` for vanilla DX11. CSP is the requirement; the hosted GR86 is the AssettoWorld 2.0.1 files.

Server join checksum is each car’s `data.acd`. Pack/deploy keeps Steam install = zip inner `data.acd` = slim `/var/lib/ac-host/content/cars/<id>/data.acd`.
