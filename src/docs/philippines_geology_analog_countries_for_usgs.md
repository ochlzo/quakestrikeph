# Countries and Regions with Philippines-Like Geological Features for USGS Earthquake Data

**Purpose:** Identify countries/regions whose earthquake records are geologically useful analogs for the Philippines, especially for aftershock analysis or model training using the USGS earthquake catalog.

**Main recommendation:** Do **not** filter only by country name. Use country/region as a first-pass filter, then refine by **tectonic setting**, **plate-boundary type**, and **geographic polygons/bounding boxes**.

---

## 1. What “similar to the Philippines” should mean

For earthquake-data selection, “similar to the Philippines” should be based on tectonic and seismotectonic features, not just proximity or being in the Pacific Ring of Fire.

The Philippines is a strong example of a **complex island-arc plate-boundary system**. Key traits include:

- **Active subduction zones** on both sides of the archipelago.
- **Opposite-facing subduction systems**, including the Philippine Trench/East Luzon Trough to the east and the Manila, Negros, Sulu, and Cotabato trench systems to the west.
- A major transform/strike-slip structure: the **Philippine Fault**.
- **Frequent shallow, intermediate-depth, and deep earthquakes**, with seismicity extending to hundreds of kilometers depth in some Philippine Sea Plate boundary regions.
- **Volcanic-arc activity** associated with subduction.
- A complicated plate-boundary environment involving the Philippine Sea Plate, Sunda Plate/Eurasian margin, and surrounding microplate/block interactions.

Because of this, the best analog countries are not merely countries that have earthquakes. They should have one or more of the following:

1. Subduction-zone earthquakes.
2. Island-arc or archipelagic volcanic arcs.
3. Major strike-slip or transform faults cutting the arc or nearby plate boundary.
4. Plate-boundary complexity involving microplates or multiple interacting plates.
5. Shallow-to-deep seismicity, including interface, intraslab, and crustal events.
6. Frequent aftershock-producing moderate to large earthquakes.

---

## 2. Recommended country/region shortlist

### Tier 1 — Strongest analogs

These should be the first regions considered for Philippines-like earthquake data.

| Country / region | Why it is a strong analog | Recommended use |
|---|---|---|
| **Indonesia** | Archipelagic subduction setting with volcanic arcs, megathrust segments, strike-slip faults, complex plate boundaries, shallow crustal earthquakes, intraslab earthquakes, and large aftershock sequences. Sumatra, Java, Nusa Tenggara, Sulawesi, Molucca, and Banda are especially relevant. | **Primary analog.** Use region-specific polygons. Do not treat all of Indonesia as equally Philippines-like. |
| **Japan** | Island-arc country crossing several major plates, including the Pacific Plate and Philippine Sea Plate. It has subduction zones, volcanic arcs, megathrust earthquakes, crustal earthquakes, and deep slab seismicity. Ryukyu, Nankai, Izu-Bonin, and Japan Trench areas are most useful. | **Primary analog.** Best for subduction, arc, crustal faulting, and aftershock behavior. |
| **Taiwan region** | Tectonically close to the northern Philippine system. Taiwan is at the Eurasian–Philippine Sea Plate boundary and involves arc-continent collision, Philippine Sea Plate interactions, and strong crustal seismicity. | **Primary/near-field analog.** Include as a technical seismic region if your system supports region-based filtering. |
| **Papua New Guinea** | Complex convergent plate-boundary zone with subduction, microplates, major faults, island arcs, and frequent large earthquakes. New Britain, Bougainville, and Bismarck/Solomon Sea plate-boundary zones are especially useful. | **Primary to secondary analog.** Strong match for complex island-arc and subduction settings. |

---

### Tier 2 — Good secondary analogs

These are useful but should usually be weighted lower than Indonesia, Japan, Taiwan, and Papua New Guinea.

| Country / region | Why it is useful | Recommended use |
|---|---|---|
| **Solomon Islands** | Subduction-related island chain with frequent large earthquakes, tectonic microplates, and strike-slip components between island chains. | **Secondary analog.** Useful for island-arc aftershock behavior and plate-boundary complexity. |
| **Vanuatu** | Highly seismic subduction-zone island arc with active volcanoes, multiple faults, microplates, and tsunami risk. | **Secondary analog.** Strong for subduction/volcanic-arc seismicity. |
| **Tonga** | Tonga-Kermadec subduction zone produces deep subduction earthquakes, shallow great earthquakes, tsunamis, and active volcanism. | **Secondary analog.** Useful for subduction physics, but less similar to the Philippines’ multi-trench archipelago. |
| **New Zealand** | Has Hikurangi subduction, the Alpine Fault, volcanic/geothermal systems, and Pacific–Australian plate-boundary deformation. | **Use carefully.** Useful but should probably be treated as a separate tectonic class because it includes more continental collision/transform deformation than the Philippines. |

---

## 3. Regions to avoid as primary analogs

These places are seismically important but are less Philippines-like for model training if mixed without labels.

| Region | Why not primary |
|---|---|
| **Chile / Peru / Andes** | Major subduction system, but mainly continental-margin subduction, not island-arc archipelago + multi-trench + Philippine-Fault-style setting. |
| **Mexico / Central America** | Useful for subduction studies, but more continental-margin and volcanic-belt dominated. Use only as a separate tectonic class. |
| **Alaska / Aleutians** | Island-arc subduction exists, but the regional geometry, climate, crustal context, and plate-boundary structure differ substantially from the Philippines. |
| **California / Turkey** | Good for strike-slip earthquakes, but not good full analogs because they lack the Philippines’ subduction-island-arc system. |

---

## 4. Practical USGS data-filtering strategy

### A. Avoid country-only filtering

USGS earthquake records are best filtered with:

- latitude/longitude bounding boxes,
- radius searches around mainshocks,
- custom tectonic-region polygons,
- depth ranges,
- magnitude thresholds,
- time windows after mainshocks.

Country labels are too coarse. For example:

- Indonesia includes both highly relevant arc/subduction zones and less relevant stable interiors.
- Japan includes several different tectonic regimes.
- New Zealand includes subduction, transform, and continental collision behavior.

### B. Suggested tagging schema

For your QuakeStrike PH dataset, tag each earthquake or sequence with tectonic context.

```yaml
country_or_region: Indonesia | Japan | Taiwan | Papua New Guinea | Solomon Islands | Vanuatu | Tonga | New Zealand
tectonic_similarity_to_philippines: high | medium | low
tectonic_class:
  - subduction_interface
  - intraslab
  - shallow_crustal
  - strike_slip_arc_fault
  - volcanic_arc_related
  - collision_zone
is_island_arc: true | false
has_active_volcanism: true | false
has_major_strike_slip_faulting: true | false
has_microplate_complexity: true | false
depth_class: shallow | intermediate | deep
mainshock_magnitude: number
aftershock_window_hours: 24 | 72 | 168 | 720
```

### C. Recommended event groups

For a first research-backed dataset, start with:

```text
Primary Philippines-like pool:
- Philippines
- Indonesia: Sumatra, Java, Nusa Tenggara, Sulawesi, Molucca, Banda
- Japan: Ryukyu, Nankai, Izu-Bonin, Japan Trench
- Taiwan region
- Papua New Guinea: New Britain, Bougainville, Bismarck/Solomon Sea margins

Secondary Philippines-like pool:
- Solomon Islands
- Vanuatu / New Hebrides arc
- Tonga-Kermadec
- New Zealand: Hikurangi + selected Alpine Fault/crustal events as separate labels
```

---

## 5. Suggested scoring matrix

Use a simple score to decide whether a country/region should enter your training pool.

| Criterion | Weight | Reason |
|---|---:|---|
| Active subduction zone | 3 | Core feature of Philippine seismicity. |
| Island-arc or archipelagic volcanic arc | 3 | Strongly matches Philippine tectonic geography. |
| Major strike-slip/transform faulting | 2 | Important because the Philippine Fault is a major active structure. |
| Microplate or multi-plate complexity | 2 | Philippines is not a simple one-trench system. |
| Shallow + intermediate/deep seismicity | 2 | Helps capture interface, intraslab, and crustal earthquake behavior. |
| Frequent M5+ to M7+ sequences | 2 | Important for aftershock modeling. |
| Continental-margin dominant setting | -2 | Penalize because it is less Philippines-like. |
| Pure transform setting without subduction | -3 | Not a full analog for Philippine earthquake generation. |

### Example interpretation

| Region | Expected score | Interpretation |
|---|---:|---|
| Indonesia arc regions | Very high | Strong analog. |
| Japan arc/subduction regions | Very high | Strong analog. |
| Taiwan region | High | Strong northern-Philippine-adjacent analog. |
| Papua New Guinea arc regions | High | Strong analog, especially complex plate-boundary zones. |
| Solomon Islands / Vanuatu | Medium-high | Good secondary analogs. |
| Tonga-Kermadec | Medium | Good subduction analog, less similar archipelago complexity. |
| New Zealand | Medium | Useful but should be separated by tectonic class. |
| Chile / Peru | Medium-low for this purpose | Strong subduction, weak Philippines-style archipelago match. |
| California / Turkey | Low | Strike-slip analog only, not full geological analog. |

---

## 6. Recommendation for QuakeStrike PH

For QuakeStrike PH, use a two-layer dataset design:

### Layer 1: Philippines-specific data

This should remain the highest-priority data because it captures local fault geometry, trench configuration, slab behavior, crustal properties, and reporting/catalog effects.

### Layer 2: Philippines-like analog data

Use analog data to improve model generalization, especially for rare large mainshocks and aftershock sequences.

Recommended analog order:

1. **Indonesia**
2. **Japan**
3. **Taiwan region**
4. **Papua New Guinea**
5. **Solomon Islands**
6. **Vanuatu**
7. **Tonga-Kermadec**
8. **New Zealand**, separated into subduction and transform/collision classes

### Layer 3: Non-analog comparison/control data

Keep regions like Chile, Peru, Mexico, Alaska, California, and Turkey as comparison groups, not primary training analogs. They can help test whether your model is overfitting to “earthquakes in general” rather than Philippines-like tectonic behavior.

---

## 7. Example USGS API approach

USGS Earthquake Catalog API documentation:

```text
https://earthquake.usgs.gov/fdsnws/event/1/
```

Example query structure:

```text
https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=YYYY-MM-DD&endtime=YYYY-MM-DD&minmagnitude=4.5&minlatitude=...&maxlatitude=...&minlongitude=...&maxlongitude=...
```

For aftershock studies, query around each mainshock using radius and time windows:

```text
https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=<mainshock_time>&endtime=<mainshock_time_plus_7_days>&latitude=<mainshock_lat>&longitude=<mainshock_lon>&maxradiuskm=300&minmagnitude=2.5
```

Then label events by:

- distance from mainshock,
- elapsed time after mainshock,
- magnitude difference from mainshock,
- depth difference,
- tectonic class,
- whether the event is inside the selected analog tectonic region.

---

## 8. Sources

1. U.S. Geological Survey. **Seismicity of the Earth 1900–2012: Philippine Sea Plate and Vicinity**. USGS Open-File Report 2010-1083-M. DOI: https://doi.org/10.3133/ofr20101083M  
   URL: https://pubs.usgs.gov/publication/ofr20101083M

2. U.S. Geological Survey. **Seismicity of the Earth 1900–2012: Sumatra and Vicinity**. USGS Open-File Report 2010-1083-L. DOI: https://doi.org/10.3133/ofr20101083L  
   URL: https://pubs.usgs.gov/publication/ofr20101083L

3. U.S. Geological Survey. **Seismicity of the Earth 1900–2007: Japan and Vicinity**. USGS Open-File Report 2010-1083-D. DOI: https://doi.org/10.3133/ofr20101083D  
   URL: https://www.usgs.gov/publications/seismicity-earth-1900-2007-japan-and-vicinity

4. U.S. Geological Survey. **Earthquake Catalog API Documentation**.  
   URL: https://earthquake.usgs.gov/fdsnws/event/1/

5. EarthScope / IRIS. **Solomon & Vanuatu Islands: Earthquakes & Tectonics**.  
   URL: https://www.iris.edu/hq/inclass/animation/solomon__vanuatu_islands_earthquakes__tectonics

6. Vanuatu Meteorology and Geo-Hazards Department. **Earthquake Info**.  
   URL: https://www.vmgd.gov.vu/learn-more/earthquake-info

7. EarthScope / IRIS. **Tonga-Kermadec Subduction Zone: Earthquakes, Tsunami, and Volcanoes**.  
   URL: https://www.iris.edu/hq/inclass/animation/tongakermadec_subduction_zone_earthquakes_tsunami_and_volcanoes

8. GNS Science / Earth Sciences New Zealand. **Earth Dynamics**.  
   URL: https://www.gns.cri.nz/our-science/land-and-marine-geoscience/earth-dynamics/

9. GNS Science / Earth Sciences New Zealand. **Hikurangi Subduction Zone**.  
   URL: https://www.gns.cri.nz/our-science/land-and-marine-geoscience/earth-dynamics/hikurangi-subduction-zone/

10. GNS Science / Earth Sciences New Zealand. **Alpine Fault**.  
    URL: https://www.gns.cri.nz/our-science/land-and-marine-geoscience/earth-dynamics/alpine-fault/

11. National Geographic Society. **Plate Tectonics and the Ring of Fire**. Last updated June 17, 2025.  
    URL: https://education.nationalgeographic.org/resource/plate-tectonics-ring-fire/

---

## 9. Bottom line

For USGS earthquake data meant to support Philippines-focused modeling, the best analogs are:

```text
Indonesia, Japan, Taiwan region, Papua New Guinea, Solomon Islands, Vanuatu, Tonga, and selected New Zealand regions.
```

The most scientifically defensible approach is not “countries like the Philippines,” but **tectonic regions like the Philippines**: subduction-related island arcs with active volcanism, major crustal/strike-slip faults, and complex multi-plate seismicity.
