QUAKESTRIKE PH: A WEB-BASED AFTERSHOCK LIKELIHOOD FORECASTING
SYSTEM USING PHIVOLCS EARTHQUAKE DATA
An Undergraduate Capstone Project
presented to the
Information Technology Department
Bicol University College of Science
Legazpi City
In Partial Fulfillment of the
Requirements for the Degree of
Bachelor of Science in Information Technology
Armenta, Sean Dylan L.
Buergo, Chenie Niña E.
Candelaria, John Benedict B.
Pispis, Dan Emanuel G.

TABLE OF CONTENTS
TABLE OF CONTENTS ii
LIST OF TABLES v
LIST OF FIGURES vi
1 INTRODUCTION 1
1.1 Background of the Study 1
1.2 Objectives of the Study 4
1.3 Significance of the Study 5
1.4 Scope and Delimitations 7
2 THEORETICAL FRAMEWORK 10
2.1 Review of Related Literature 10
2.1.1 Earthquake Monitoring and Philippine Seismicity 10
2.1.2 Mainshock-Aftershock Sequences 12
2.1.3 Statistical and Probabilistic Aftershock Forecasting 14
2.1.4 Machine Learning and Clustering Approaches in Earthquake Analysis 19
2.1.5 Web-Based Earthquake Information and Visualization Systems 29
2.2 Gaps Bridged by the Study 33
2.3 Concept of the Study 34
Figure 1. Conceptual Framework 34
2.4 Definition of Terms 35
3 MATERIALS AND METHODS 38
ii

3.1 Materials 38
3.1.1 Software 38
3.1.2 Hardware 40
3.2 Software Methodology 41
3.2.1 Requirements Planning 43
Figure 2. Interview with PHIVOLCS-SOEPD 44
3.2.2 User Design 44
Figure 3. Landing Page 46
Figure 4. Dashboard 47
Figure 5. Event List 47
Figure 6. Forecast History 48
Figure 7. Forecast View 48
Figure 8. Forecast Detailed View 49
3.3 Evaluation Procedure 50
REFERENCES 53
APPENDICES 61
Appendix A: Request Letter for Earthquake Catalog 65
Appendix B: Request Letter for Bogo, Cebu 67
Appendix C: Activity Flow Diagram 68
Appendix D: Context Flow Diagram 69
Appendix E: Use Case Diagram 70
Appendix F: Entity Relationship Diagram 71
iv

Appendix G: Deployment Diagram 72
iv

LIST OF TABLES

| Table 1.  | Software Requirements    | 37  |
| --------- | ------------------------ | --- |
| Table 2.  | Hardware Specifications  | 38  |
| Table 3.  | Likert Scale             | 46  |

v

LIST OF FIGURES
| Figure 1.   | Conceptual Framework           | 33  |
| ----------- | ------------------------------ | --- |
| Figure 2.   | Interview with PHIVOLCS-SOEPD  | 44  |
| Figure 3.   | Dashboard                      | 46  |
| Figure 4.   | Forecast History               | 46  |
| Figure 5.   | Forecast View                  | 47  |
| Figure 6.   | Forecast Detailed View         | 47  |

vi

1 INTRODUCTION
1.1 Background of the Study
Communities are still impacted by earthquakes not only by the immediate shaking of the
ground but also by the disturbance they cause prior to, during, and following the occurrence.
Communities' awareness, access to danger information, building safety, and local disaster
preparedness all influence how prepared they are for an earthquake. When an earthquake occurs,
people must act fast to protect themselves, evacuate if needed, and make sure family members
are safe. Even after the shaking stops, the repercussions frequently persist, including damaged
homes, disrupted services, hazardous buildings, loss of livelihoods, psychological stress, and
concern about potential aftershocks.
The effects of earthquakes on communities can be severe and long-lasting, as seen by
recent seismic disasters. One of the deadliest and most expensive natural catastrophes in recent
memory, the 2023 sequence of earthquakes in Turkey and Syria claimed about 56,000 lives and
inflicted billions of dollars' worth of damage (Centre for Research on the Epidemiology of
catastrophes [CRED], 2024). In addition to physical harm, impacted populations endure stress,
grief, terror, and dislocation while they heal. According to Garfin and Silver (2023), recurrent
stressors like losing family members, damaged surroundings, temporary shelter circumstances,
and uncertainty following the disaster can have a significant negative impact on an earthquake
survivor's mental health. These consequences demonstrate that earthquakes are social and
communal catastrophes in addition to geological occurrences.
This challenge is increased by aftershocks since they prolong the time of hazard
following the mainshock. Smaller subsequent earthquakes can nonetheless harm vulnerable
structures, delay rescue and clearing operations, disrupt recovery efforts, and raise public worry

even if the biggest earthquake typically gets the most attention. According to Zhang et al. (2025),
aftershock sequences may make structures that have previously been impacted by a mainshock
more vulnerable. This implies that the time following a powerful earthquake is neither
immediately safe nor routine for locals. Fearing another earthquake, many people would be
reluctant to go home, sleep outside, stay away from damaged structures, or wait for official
updates all the time.
Modern earthquake science concentrates on probabilistic forecasting rather than precise
earthquake prediction because aftershocks are unpredictable. According to Hardebeck et al.
(2024), aftershock forecasting calculates the likelihood, anticipated quantity, or rate of
aftershocks within a specified time and magnitude range. These predictions do not pinpoint the
precise time, position, or size of a future earthquake, but they are helpful for making decisions
during response and recovery. Communities want information that promotes readiness without
fostering false assurance, which makes this distinction crucial for public communication.
However, the clarity with which aftershock information is conveyed determines its
usefulness. According to Schneider et al. (2022), if aftershock forecast maps and uncertainty data
are presented in extremely technical ways, non-expert users may find them challenging to
comprehend. People may overreact, misjudge the risk, or rely on unofficial sources when they
find it difficult to understand probability. This issue is particularly crucial following a felt
earthquake, when locals want to know if they should stay vigilant, stay away from damaged
buildings, gather emergency supplies, or keep an eye on official recommendations. As a result,
information about the likelihood of an aftershock should be communicated using clear
categories, visual signals, and plain language.
2

Because the Philippines is so vulnerable to seismic hazards, there is a critical need for
comprehensible earthquake and aftershock information. Through the Philippine Seismic
Network, the Philippine Institute of Volcanology and Seismology (PHIVOLCS) keeps an eye on
earthquake activity and offers official earthquake data, including date, time, location, depth, and
magnitude (PHIVOLCS, n.d.). Due to active faults and subduction zones, the nation frequently
experiences earthquakes, and many communities in Mindanao, Visayas, and Luzon reside close
to potentially seismically active locations. Stronger earthquakes can still result in significant
damage and public concern, even if the majority of documented earthquakes are minor or unfelt.
The 2020 magnitude 6.6 Masbate earthquake, which resulted in fatalities, injuries, and
damage to houses, schools, and public infrastructure, serves as a local example. Numerous
aftershocks followed the incident, demonstrating how earthquake effects might persist beyond
the mainshock (PHIVOLCS, 2020). Aftershocks can make recovery more difficult for impacted
communities since people may still be evaluating damage, retrieving possessions, fixing homes,
or determining whether it's safe to go back inside. This circumstance emphasizes how crucial it
is to offer comprehensible aftershock likelihood counsel in addition to information about
earthquake events.
Although crucial earthquake information is being provided via government bulletins and
monitoring systems, many users still require assistance in deciphering the implications of a
recent earthquake. While earthquake characteristics and safety alerts are frequently reported by
current systems, they do not always provide straightforward aftershock likelihood indications
that might assist the public in understanding the potential of further earthquakes. People may
therefore rely on their own presumptions, hearsay, or social media posts, which can add to
uncertainty and needless anxiety during a time that is already stressful.
3

To address this gap, this study proposes QuakeStrike PH: A Web-Based Aftershock
Likelihood Forecasting System Using PHIVOLCS Earthquake Data. By generating
probability-based aftershock likelihood outputs within a specified time range using PHIVOLCS
earthquake catalog data, the system seeks to enhance public awareness of seismic activity. It
doesn't try to forecast the precise moment, place, or size of upcoming earthquakes. Rather, it
concentrates on using an interactive map, searchable event list, event details, filters, and
prediction history to show aftershock likelihood in a more comprehensible and accessible
manner. By using this method, QuakeStrike PH functions as a helpful information system that
aids in bridging the knowledge gap between technical earthquake data and community-level
comprehension.
1.2 Objectives of the Study
To develop QuakeStrike PH, a countrywide seismic tracking instrument that can detect
aftershock sequences and generate probability-based aftershock likelihood indicators to improve
the public’s understanding and interpretation of seismic activity in the Philippines. Specifically, it
aims to:
1. To gather, clean, and prepare PHIVOLCS earthquake catalog data by collecting
earthquake records and organizing the required data fields, including date-time,
latitude, longitude, depth, and magnitude, for aftershock likelihood forecasting.
2. To train and compare machine learning models using processed historical
earthquake data by applying Random Forest and LightBGM models for
estimating aftershock likelihood within 24 hours, likelihood within predefined
distance ranges from the epicenter, and possible maximum aftershock magnitude.
4

3. To develop the QuakeStrike PH web-based system with the following core
features:
a. An interactive website interface for accessing earthquake and aftershock
likelihood information;
b. A map-based plotting feature for visualizing earthquake events;
c. A forecasting feature that displays percentage-based aftershock likelihood
outputs; and
d. A forecast history feature that stores and displays previous earthquake
likelihood results.
4. To identify historical mainshock-aftershock relationships in the earthquake
catalog by applying the Zaliaping and Ben-Zion (2013) nearest-neighbor cluster
identification method as a preprocessing step for labelling and structuring
earthquake event relationships.
5. To evaluate the system and forecasting model using appropriate evaluation
standards, including machine learning performance metrics such as accuracy,
precision, recall, F1 score, ROC-AUC or PR-AUC for classification outputs, and
MAE, RMSE, and R² for regression outputs, together with ISO/IEC 25010
software quality criteria for assessing the system’s functional suitability, usability,
and performance efficiency.
1.3 Significance of the Study
This study aims to identify the aftershock sequences and generate probability-based
aftershock likelihood indicators to support public understanding of seismic activity. In particular,
the present study will benefit the following beneficiaries:
5

General Public. The general public is the primary beneficiary of this study. The system
may provide users with easier access to earthquake information and make data on possible
aftershock threats more understandable. Through the map display, filter features, and the
simplified likelihood indicators (Low, Medium, and High), users will better understand seismic
data and can better make informed choices regarding safety and emergency preparedness after
earthquakes. Also, the public can benefit from the presence of a scientifically-based source of
information to eliminate the guessing.
Community and Society. By encouraging awareness and readiness regarding seismic
threats, the study may benefit the larger community. The system promotes proactive behavior
among individuals and communities by improving the accessibility and interpretability of
earthquake data. This could boost societal resilience overall by enhancing preparedness for
disasters, lowering anxiety during seismic occurrences, and encouraging more responsible
information sharing.
Disaster Risk Reduction and Management Offices / Local Government Units. This
may assist local governments and agencies in reducing and managing disaster risks as it would
augment the monitoring of earthquake and aftershocks conditions. In the post-earthquake setup,
the system might help enhance situational awareness and facilitate decision-making.
Additionally, by providing technical earthquake data in a way that is simpler for the general
public to comprehend, it may improve communication efforts.
Higher Education Institutions. The study may benefit higher education institutions by
serving as a reference for academic projects related to disaster risk reduction, seismic
monitoring, data science, and web-based information systems. Additionally, it might promote
interdisciplinary research in the fields of geoscience, public safety, information technology, and
6

community readiness. Future academic projects aiming at creating technology-based tools for
public awareness and disaster-related decision assistance may benefit from the study.
College of Science. This study may benefit the College of Science by contributing to its
research output in fields of computing, data-driven systems, and community-oriented
technologies. It might be an illustration of how information technology can be used to address
scientific and societal issues, especially in the communication of aftershock likelihood and
earthquake awareness. Additionally, the initiative can serve as a basis for future student research
that integrates data analysis, software development, and public service.
Future Researchers. Future researchers in the fields of geology, data science, and
information technology may find this work useful. The techniques employed to identify
aftershock sequences and produce probabilistic likelihood indicators could serve as basis for
additional study and system enhancements. By strengthening forecasting models, increasing
system usability, or extending its applicability to other areas or disaster-related scenarios, future
researchers may build on this work.
1.4 Scope and Delimitations
The study focuses mainly on developing a web-based application specialized in seismic
monitoring and aftershock likelihood forecasting within the Philippine Area of Responsibility
(PAR). Using earthquake catalog data from the Philippine Institute of Volcanology and
Seismology (PHIVOLCS), the system aims to process earthquake records, analyze
spatiotemporal patterns, and generate percentage-based aftershock likelihood outputs. These
outputs include the probability of at least one aftershock occurring within estimated distance
7

ranges from the epicenter and the possible maximum aftershock magnitude within a 24-hour
time window.
An automated workflow for data processing is also part of the system. A scraping process
will be used to gather newly accessible earthquake records from PHIVOLCS. The system will
use Celery workers to queue a forecasting task when a new seismic event is identified, enabling
the aftershock likelihood model to automatically produce updated prediction outputs. This
eliminates the need for manual processing for each new event, allowing the system to update its
displayed earthquake information and likelihood results.
The Zaliapin nearest-neighbor clustering method is used as a preprocessing step in the
system’s technological framework to find past mainshock-aftershock correlations in the
earthquake database. The processed data will then be utilized to estimate percentage-based
aftershock likelihood outcomes using machine learning. The model will be trained and tested
using historical earthquake catalog records and evaluated using appropriate performance metrics
based on the final forecasting task.
The interactive user interface of the system features a searchable event list,
percentage-based likelihood outputs, a mapping component, and information of specific
earthquake events. Earthquake events can be filtered by magnitude, depth, location, and
date/time. In order to make it easier for users to understand probabilistic outcomes, the interface
is made to display aftershock likelihood information using visual cues.
The system is constrained by multiple delimitations with these qualities. Its findings are
solely probability-based, and it is not intended to forecast the precise timing, location, or size of
future earthquakes. The study does not address other seismic concepts like tsunami forecasting,
volcanic activity, structural damage assessment, or emergency response planning; instead, it
8

concentrates solely on aftershock risk within a 24-hour forecast frame. Rather, it is merely an
extra tool for displaying and analyzing data on the likelihood of earthquakes and aftershocks.
9

2 THEORETICAL FRAMEWORK
The review of related literature explores existing studies and concepts related to
earthquake monitoring, aftershock sequences, statistical and probabilistic forecasting, machine
learning, clustering methods, and web-based earthquake information systems. It discusses how
seismic data can be analyzed and presented to support public understanding, especially in
interpreting possible aftershock activity after a mainshock. The review also examines related
systems and forecasting approaches to identify the gap the QuakeStrike PH aims to address.
2.1 Review of Related Literature
2.1.1 Earthquake Monitoring and Philippine Seismicity
Earthquake monitoring and aftershock forecasts are key components of seismic risk
management. According to the review of Hardebeck et al. (2024) in the Annual Review of Earth
and Planetary Sciences, statistical models developed from an analysis of earthquake catalogs
assessing aftershock likelihood based on time and spatial distribution—as well as the magnitude
of earthquakes—are the most commonly referenced sources of data for forecasting aftershocks.
As a result, many countries utilize these predictions in their decision making processes when
responding to disasters. Aftershocks may further compromise damaged structures and other
critical infrastructures.
The United States Geological Survey (USGS) demonstrates how statistical aftershock
forecasting models are operationalized in real-world seismic monitoring systems. By utilizing
historical earthquake data, the USGS generates probabilistic aftershock forecasts that support
decision-making during earthquake response and recovery. These models are continuously
refined through the integration of physical modeling approaches and modern machine learning

techniques, reflecting ongoing advancements in seismic research. Such developments highlight
the evolving role of technology in seismic monitoring systems, particularly in enhancing
predictive capabilities, improving forecasting accuracy, and enabling more effective hazard
assessment.
Earthquake monitoring systems are being used more frequently at the regional level for
quick hazard evaluation, especially in seismically active areas. Within hours of a mainshock,
early aftershock sequences can be evaluated to quickly identify seismic intensity, enabling the
identification of severely impacted areas and facilitating prompt emergency response, according
to a study by Zhao et al. (2023). The study emphasizes the significance of ongoing seismic
monitoring and data availability by highlighting how adequate aftershock data enables quicker
and more accurate assessment of earthquake impacts. Additionally, a study published in
Scientific Reports highlights the importance of dense and well-distributed seismic networks for
successful seismic monitoring, since wider spatial coverage enhances the data collecting,
detection capacity, and overall analysis of seismic activity across regions (Diaz, 2024). These
results highlight the significance of data-driven, localized monitoring systems, especially in
earthquake-prone areas where fast and accurate seismic data is essential for hazard assessment
and disaster risk reduction.
The Philippine Institute of Volcanology and Seismology (PHIVOLCS), which runs a
nationwide seismic network intended to deliver precise and fast information on earthquake and
tsunami events, is principally responsible for earthquake monitoring in the Philippines. The
organization operates a large number of seismic stations around the nation, and data is sent in
real time to centralized monitoring facilities for analysis and subsequently uploaded to their
website for public information. These technologies guarantee the ongoing gathering of seismic
11

data, creating earthquake catalogs that contain important information like location, depth, and
magnitude.
Furthermore, the nation’s capacity to identify and evaluate seismic activity has greatly
increased thanks to the growth of seismic monitoring stations and the incorporation of
contemporary equipment. The Philippine Institute of Volcanology and Seismology (PHIVOLCS)
states that the installation of more seismic stations improved the country’s seismic monitoring
network in order to guarantee more precise and fast earthquake information (PHIVOLCS, n.d.).
By offering vital insights into earthquake behavior and trends, these advancements aid in risk
mitigation, hazard mapping, and disaster preparedness. A dependable and effective earthquake
monitoring system is even more important because the Philippines is situated along the Pacific
Ring of Fire, where a large percentage of earthquakes worldwide occur (de Freitas et al., 2024).
All things considered, the literature emphasizes how crucial reliable monitoring systems, backed
by precise data and cutting-edge analytical techniques, are to comprehending seismicity and
creating useful aftershock forecasting applications.
2.1.2 Mainshock-Aftershock Sequences
According to the Japan Meteorological Agency (JMA), a large earthquake is usually
followed by a series of smaller earthquakes near the epicenter. These are referred to as the
mainshock and aftershocks, and this pattern is known as a mainshock-aftershock sequence. The
area where aftershocks occur is called the aftershock area. In Japan, aftershock information is
commonly based on data collected within about 24 hours after the mainshock. In the Philippine
setting, PHIVOLCS recognizes that aftershocks may still occur for days, weeks, months, or even
12

longer depending on the sequence. This difference shows the importance of considering local
seismic behavior when developing an aftershock-related system.
Shu and Song (2026) used the PEER-NGA-West2 database, which contains nearly 20,000
ground motion records. However, the database has limitations because it does not clearly label
whether a record is from a mainshock or an aftershock. The study also focused only on
sequences with one mainshock and the largest following aftershock. The researchers suggested
that future studies should include multiple aftershocks to better represent the swarm-like
behavior that can occur after a major earthquake.
Shu et al. (2026) also tested several predictive techniques, including decision trees, neural
networks, and regression models. Their findings showed that decision trees performed well in
predicting aftershock magnitude, significant duration, and fault mechanism. Neural networks
were also explored, but they were found to be less effective for the specific model structure used
in the study. This is relevant to QuakeStrike PH because it shows that simpler machine learning
models may still be useful for aftershock-related analysis when the available features are
properly selected.
Zhong et al. (2022) used machine learning, particularly Light Gradient Boosting Machine
(LightGBM), to improve the prediction of mainshock-aftershock sequences. Their framework
used eight seismic features, which expanded the limited parameter sets commonly used in
traditional forecasting models. The study also transformed classical seismic observations, such as
values derived from the Modified Omori Law and Gutenberg-Richter relationship, into inputs for
the LightGBM model. This allowed the model to learn non-linear patterns from early seismic
activity after the mainshock.
13

The study of Zhong et al. (2022) is also useful because it focused on early-stage
forecasting using data from the first hour after the mainshock. However, the model was trained
and tested using earthquake sequences from the Sichuan-Yunnan region in China. This leaves a
spatial and geological gap because the same model may not automatically perform well in other
tectonic settings. In relation to QuakeStrike PH, this supports the need to study aftershock
sequence detection using Philippine earthquake catalog data, since the country has its own
seismic characteristics, fault systems, and subduction zones.
2.1.3 Statistical and Probabilistic Aftershock Forecasting
Statistical and probabilistic aftershock forecasting has become an important foundation in
earthquake science because aftershocks cannot be predicted with exact certainty in terms of their
precise time, location, and magnitude. Instead of deterministic prediction, established aftershock
models estimate the likelihood, rate, expected number, or possible magnitude range of
aftershocks after a mainshock. These methods are commonly based on known statistical patterns
in earthquake sequences, including Omori’s Law, which describes the decay of aftershock
frequency over time; the Gutenberg-Richter law, which explains the relationship between
earthquake magnitude and frequency; and probabilistic models such as the Reasenberg-Jones
model and the Epidemic-Type Aftershock Sequence (ETAS) model. Declustering methods such
as Gardner-Knopoff are also relevant because they help separate dependent events, such as
aftershocks, from independent background earthquakes before forecasting or seismicity analysis
is performed. This subtopic is relevant to QuakeStrike PH because the proposed system does not
aim to predict earthquakes exactly, but instead seeks to detect possible mainshock-aftershock
sequences from PHIVOLCS earthquake catalog data and present aftershock likelihood
14

information in a simple and understandable way. This makes the topic directly relevant to
QuakeStrike PH, since the system focuses on aftershock likelihood estimation rather than exact
earthquake prediction.
Hardebeck et al. (2024) reviewed the scientific foundation of aftershock forecasting and
emphasized that most operational aftershock forecasts are still based on statistical models
developed in the 1980s. The review explained that these models remain useful because
aftershock behavior follows observable statistical regularities, particularly the decrease of
aftershock rate with time and the relationship between earthquake magnitude and event
frequency. The study also discussed current efforts to improve aftershock forecasting through
statistical, physical, and machine learning approaches, but noted that statistical models remain
the strongest operational baseline.
This review is relevant to QuakeStrike PH because it supports the use of likelihood-based
forecasting rather than exact earthquake prediction. Since the proposed system will communicate
aftershock likelihood within 24 hours, the study provides a strong global basis for explaining
why aftershock outputs should be interpreted as probabilities or expected tendencies. In relation
to QuakeStrike PH, the review supports the idea that the system may use historical earthquake
behavior, temporal decay, magnitude-frequency patterns, and aftershock productivity to estimate
likely aftershock activity after a mainshock.
The United States Geological Survey (USGS, n.d.) explains that its public aftershock
forecast product uses statistical models such as Reasenberg-Jones and ETAS to estimate
aftershock behavior after a mainshock. The scientific background of the USGS forecast describes
the Reasenberg-Jones rate equation, which estimates the rate of aftershocks of at least a given
15

magnitude at a given time after the mainshock. This model combines important aftershock
characteristics, including magnitude dependence and the decay of aftershock rate over time.
This source is relevant because it shows that probabilistic aftershock forecasting is not
only theoretical but already applied in an operational public-facing system. For QuakeStrike PH,
this supports the decision to avoid deterministic wording such as “predicting the exact next
earthquake” and instead use terms such as likelihood, expected activity, forecast window, and
probability-based output. The USGS model also provides a useful conceptual basis for
presenting outputs such as expected aftershock count or likelihood level within a defined time
window.
Bi, Song, and Cao (2024) examined the declustering characteristics of the North China
Plain seismic belt and analyzed how different declustering methods affect probabilistic seismic
hazard analysis. The study used four declustering methods: Gardner-Knopoff, Reasenberg,
nearest-neighbor, and stochastic declustering. The authors explained that accurately identifying
background seismicity and clustered earthquake events is important for earthquake model
construction and probabilistic seismic hazard analysis. Their study used earthquake catalog data
from 1970 to 2023 and showed that the different declustering methods produced varying
declustering ratios, background seismicity rates, and Gutenberg-Richter b-values. In particular,
the Gardner-Knopoff method removed a higher proportion of clustered events compared with
some other methods, while the Reasenberg method removed a lower proportion. The study also
found that declustering results affected seismic hazard estimates because the hazard curves were
influenced by the annual occurrence rate of background earthquakes and the Gutenberg-Richter
b-value.
16

Since QuakeStrike PH will identify possible mainshock-aftershock sequences before
generating likelihood outputs, the study supports the need to carefully select a clustering method
because the chosen method can affect how earthquake events are grouped and interpreted for
probabilistic analysis. Although Bi et al. (2024) framed their work as declustering, their study
still emphasizes the importance of distinguishing background seismicity from clustered
earthquake events and shows that different methods, including the nearest-neighbor approach,
can produce different catalog results, seismicity rates, and Gutenberg-Richter b-values.
Omi et al. (2019) developed a prototype real-time automatic aftershock forecasting
system for Japan using real-time seismicity data from the High Sensitivity Seismograph Network
of the National Research Institute for Earth Science and Disaster Resilience. The system
automatically generated rapid aftershock forecasts and began issuing time-dependent forecasts
around three hours after a mainshock, with hourly updates. The study demonstrates how
aftershock forecasting can be implemented in an Asian setting using continuously updated
earthquake data and statistical forecasting methods.
This study is relevant to QuakeStrike PH because it shows that aftershock forecasting can
be applied operationally in a country with high seismic activity, similar to the Philippines.
Although Japan has a more advanced seismic monitoring infrastructure, the study supports the
idea that earthquake catalog data can be used to produce time-dependent aftershock likelihood
information. In relation to QuakeStrike PH, this strengthens the basis for using PHIVOLCS
earthquake event data to generate updated aftershock likelihood outputs within 24 hours.
Batac (2016) analyzed the immediate aftershocks of the 15 October 2013 magnitude 7.1
Bohol earthquake in the Philippines. The study examined aftershock records using interevent
distances and interevent times and compared the behavior of the Bohol aftershock sequence with
17

previous Philippine earthquake catalog results. The study found that the aftershock records
showed strong spatiotemporal correlations, making it locally relevant for understanding how
Philippine aftershock sequences behave after a major earthquake.
This study is important to QuakeStrike PH because it provides national evidence that
Philippine aftershock sequences can be statistically analyzed using catalog-based features such
as time and distance between events. In addition, PHIVOLCS primers regularly communicate
aftershock expectations in Philippine earthquake events. For example, PHIVOLCS stated in its
2023 Offshore Surigao del Sur earthquake primer that moderate to strong aftershocks may be
expected in the epicentral area and may persist for several days to months. PHIVOLCS also
provides official earthquake bulletins containing event parameters such as hypocenter, time, and
magnitude from the Philippine Seismic Network, which are the same types of data needed for
catalog-based aftershock analysis.
These national sources are relevant because they show that aftershock information is
already part of official earthquake communication in the Philippines, but it is usually presented
as event-specific advisories rather than as an automated likelihood dashboard. In relation to
QuakeStrike PH, this supports the local gap: PHIVOLCS provides official earthquake
information and aftershock advisories, but there is room for a system that organizes earthquake
catalog data, detects possible aftershock sequences, and presents simplified aftershock likelihood
information for public interpretation.
The reviewed literature shows that statistical and probabilistic aftershock forecasting is
an established approach in earthquake science. Hardebeck et al. and the USGS aftershock
forecast sources show that operational aftershock forecasting commonly relies on statistical
models such as Reasenberg-Jones and ETAS, which estimate aftershock rates, probabilities, and
18

expected activity rather than exact future earthquakes. Studies on declustering also show that
methods such as Gardner-Knopoff and nearest-neighbor approaches are useful in separating
possible aftershocks from background seismicity before further analysis is performed.
In the Philippine context, Batac’s analysis of the 2013 Bohol aftershock sequence
provides local evidence that aftershock behavior can be studied statistically using interevent time
and distance patterns. PHIVOLCS primers and earthquake bulletins also show that aftershock
expectations are already communicated to the public, although mostly through official advisories
and event-specific updates. Together, these sources support the direction of QuakeStrike PH as a
system that detects possible aftershock sequences from Philippine earthquake catalog data and
communicates probability-based aftershock likelihood in a more understandable format.
2.1.4 Machine Learning and Clustering Approaches in Earthquake Analysis
Machine learning-based earthquake and aftershock forecasting has become increasingly
relevant as earthquake catalogs continue to grow in size and availability. Traditional statistical
approaches such as ETAS remain important in operational forecasting, but recent studies show
that machine learning can complement these methods by learning patterns from larger datasets
and using more event features. This is relevant to QuakeStrike PH because the proposed system
aims to use PHIVOLCS earthquake catalog data to detect aftershock sequences and generate
short-term aftershock likelihood estimators rather than exact earthquake predictions.
Yu et al. (2025) developed an Automated Machine Learning (AutoML)-based model for
predicting the acceleration spectrum of the largest expected aftershock. Their study emphasized
that aftershocks can cause additional damage to structures already weakened by a mainshock,
making aftershock-related forecasting important for post-earthquake risk assessment. The model
19

used 2,500 mainshock–aftershock sequence recordings from global ground-motion databases and
incorporated input features derived from the mainshock, including mainshock spectral
acceleration, moment magnitude, source-to-site distance, and average shear-wave velocity in the
top 30 meters (VS30). The study reported strong model performance, with testing R² scores
ranging from 0.85 to 0.93 across different spectral periods.
Although the study focused on forecasting aftershock ground-motion spectra rather than
aftershock count or affected radius, it remains relevant to QuakeStrike PH because it
demonstrates that machine learning can use mainshock-derived features to forecast
aftershock-related behavior. In relation to this work, QuakeStrike PH may similarly use
mainshock magnitude, depth, location, distance and radius features, and regional seismicity
characteristics as input variables for forecasting aftershock count, affected radius, and the
strongest expected aftershock magnitude.
Dascher-Cousineau et al. (2023) introduced RECAST, a deep-learning earthquake
forecasting model based on neural temporal point processes. The study argued that current
earthquake forecasting models are often constrained by statistical assumptions and may not fully
utilize the increasing size and richness of modern earthquake catalogs. RECAST was designed to
be flexible and scalable by encoding the history of past earthquakes and predicting the timing of
the next event. The model was benchmarked against a temporal ETAS model and showed
improved fit and forecast accuracy when the training catalog was sufficiently long.
This study is relevant because it strengthens the rationale for using machine learning even
when statistical models such as ETAS already exist. The authors explained that neural models
can incorporate larger datasets and additional earthquake information without requiring a fixed
functional form, while still being compared against ETAS as a scientific benchmark. For
20

QuakeStrike PH, this supports the argument that machine learning is not intended to replace
established seismological knowledge but to complement it by learning from available Philippine
earthquake catalog patterns. However, because RECAST is a deep-learning model and requires a
sufficiently large dataset, it may be more suitable as supporting literature than as the primary
capstone implementation model.
Perry and Bendick (2024) compared five commonly used earthquake declustering
algorithms: Gardner-Knopoff, Uhrhammer, Reasenberg, Zhuang et al., and Zaliapin et al. The
study explained that declustering is the process of separating dependent events, such as
aftershocks, from independent background earthquakes. The results showed that the Zaliapin et
al. nearest-neighbor approach performed well overall because it effectively removed aftershock
sequences while retaining more catalog information. The study also reported that
Gardner-Knopoff and Zhuang et al. effectively removed aftershock sequences, although they
removed more events compared with some other methods.
This study is relevant to QuakeStrike PH because the system must first identify or label
possible mainshock–aftershock sequences before training an aftershock forecasting model.
Gardner-Knopoff remains practical because it is straightforward and easier to implement for a
capstone system, especially when working with catalog fields such as date-time, latitude,
longitude, depth, and magnitude. The study also suggests that future versions of QuakeStrike PH
may compare Gardner-Knopoff with more advanced methods such as the Zaliapin
nearest-neighbor approach to improve sequence identification.
Niteesh et al. (2024) compared several regression models for earthquake prediction,
including Random Forest Regressor, Decision Tree Regressor, Linear Regressor, and a
21

regression Artificial Neural Network. The study examined how different machine learning
architectures capture relationships between independent and dependent earthquake variables.
This is relevant because it presents a clear example of applying simple regression models
to earthquake prediction. Although it is not specifically focused on Philippine aftershock
forecasting, it provides support for using regression models such as Random Forest Regressor,
Decision Tree Regressor, and Linear Regression for earthquake-related prediction tasks. In
relation to QuakeStrike PH, this supports the feasibility of using supervised regression models to
predict numerical aftershock-related outputs such as expected count, affected radius, or
maximum aftershock magnitude.
Gentili et al. (2025) applied an improved version of the NESTORE machine learning
algorithm to the Japan Meteorological Agency earthquake catalog from 1973 to 2024.
NESTORE forecasts whether a seismic cluster will become a Type A cluster, where aftershocks
reach or exceed a magnitude equal to the mainshock magnitude minus one, or a Type B cluster,
where this condition is not met. The study used a hybrid cluster identification method combining
ETAS-based stochastic declustering and graph-based selection. It also introduced REPENESE,
an outlier-detection method for imbalanced seismic cluster datasets.
The study is particularly useful for QuakeStrike PH because it is Asia-scoped and directly
focuses on strong aftershock or strong subsequent earthquake forecasting. Its forecast timing is
also relevant: the model produced useful classification results as early as six hours after the
mainshock, and the training intervals covered 6-hour windows during the first day, then daily
intervals during the first week. The authors limited the final analysis mainly to the first day
because Type A clusters became fewer after one day, indicating the importance of early
aftershock behavior. The model used features such as the number of aftershocks with magnitude
22

at least mainshock magnitude minus two, cumulative source area, normalized energy, and
spatial-temporal-magnitude distribution features. The study reported 75% correct forecasting for
Type A clusters, 96% for Type B clusters, 0.75 precision, and 0.94 accuracy six hours after the
mainshock.
In relation to QuakeStrike PH, NESTORE supports the idea of classifying aftershock
severity or strong-aftershock likelihood using early sequence features. While QuakeStrike PH
may use a simpler model such as Random Forest or Gradient Boosting regression, the
NESTORE study supports the inclusion of features such as early aftershock count, strongest
early aftershock, magnitude difference, spatial spread, cumulative seismic activity, and
short-term forecast windows such as the first 24 hours.
Zhao et al. (2021) studied aftershock spatial distribution prediction in China by
comparing different machine learning methods and feature groups. The study used 62,811
aftershocks from 171 mainshocks recorded over approximately 40 years in China. The
researchers trained several machine learning classifiers, including Naive Bayes, Support Vector
Machine, Gradient Boosting Decision Tree, k-Nearest Neighbors, Logistic Regression, and a
deep neural network model. They also used different types of input features, including
stress-change sensors, logarithmic stress values, physical quantities, mainshock magnitude, and
the distance between the grid cell and the mainshock epicenter. The study found that feature
selection was more important than the specific model used, and the combined feature set
achieved an AUC of 0.9530.
This study is relevant to QuakeStrike PH because it shows that both simple and advanced
machine learning models can analyze aftershock spatial patterns when good features are
available. The inclusion of mainshock magnitude and distance from the mainshock epicenter is
23

especially useful because these features can be derived from PHIVOLCS catalog data. In relation
to QuakeStrike PH, this supports using engineered features such as Gardner-Knopoff radius,
distance from mainshock, regional event density, and recent seismicity counts. It also supports
the view that model complexity is not the only factor; carefully designed input features may be
equally or more important for aftershock-related prediction.
Liu et al. (2024) proposed an interpretable hybrid machine learning model for aftershock
hazard mapping using multi-source data. The model integrated mainshock factors, geological
features, site characteristics, and terrain conditions through GIS technology. The study used
machine learning models such as XGBoost, LightGBM, and a stacking model, with SHAP
analysis used to explain the influence of each feature. The study addressed challenges in
aftershock prediction, including feature selection, model type, visualization of prediction results,
and interpretability of decision mechanisms.
This study is relevant to QuakeStrike PH because it connects machine learning with
map-based aftershock hazard interpretation. Since QuakeStrike PH includes an interactive map
and aftershock likelihood outputs, this study supports the use of interpretable machine learning
models and spatial features. In relation to the proposed system, the study suggests that aftershock
risk can be communicated more effectively when machine learning outputs are connected to
geographic visualization and explainable variables. Although the model is more complex than a
basic Random Forest, it supports the use of gradient-boosting models such as XGBoost and
LightGBM for future improvements.
Liao et al. (2025) investigated the 2025 M6.4 Dapu earthquake sequence in western
Taiwan using a deep-learning-empowered earthquake cataloging method. The study identified
6,805 seismic events from January 20 to 31, 2025, and achieved a completeness magnitude of
24

approximately 0.7, showing that deep learning can detect many smaller aftershocks that may not
be captured in standard catalogs. The improved catalog was used to analyze the
three-dimensional seismogenic structure of the earthquake sequence and to compare it with the
relocated instrumental earthquake catalog.
This study is relevant to QuakeStrike PH because it shows how deep learning can
improve earthquake and aftershock sequence catalogs in an Asian setting. Although it focuses on
cataloging and structural analysis rather than direct aftershock likelihood forecasting, it supports
the importance of accurate aftershock detection before sequence analysis. In relation to
QuakeStrike PH, this suggests that the quality and completeness of earthquake catalog data can
strongly affect aftershock sequence detection and model training. For the current capstone, this
supports the need to carefully clean and validate PHIVOLCS catalog data before applying
clustering and forecasting models.
Kuo-Chen et al. (2025) introduced a deep-learning-based real-time microearthquake
monitoring system (RT-MEMS) designed to generate rapid and high-resolution earthquake
catalogs. The system uses deep learning models to process continuous seismic waveform data
and pick P- and S-wave arrivals, after which earthquake events are associated and located.
RT-MEMS has been applied to background seismicity monitoring and to mainshock–aftershock
sequences in Taiwan. One related application analyzed 3,893 aftershocks within 15 days of the
2025 M6.4 Dapu earthquake.
This study is relevant because it shows that machine learning can assist in real-time
monitoring of aftershock sequences by improving event detection and catalog generation. For
QuakeStrike PH, the proposed model may not require waveform-based deep learning, but the
study supports the broader idea that earthquake and aftershock sequence analysis increasingly
25

depends on machine learning–assisted catalog development. In relation to the proposed system,
the study reinforces the importance of reliable earthquake event data, because aftershock
clustering and likelihood estimation depend on whether the catalog captures enough aftershock
activity.
Wan and Heron (2026) compared clustering techniques for identifying
mainshock–aftershock sequences in the Longmen Shan Fault Zone in China, focusing on the
2008 Wenchuan and 2013 Lushan earthquake events. The researchers applied and compared
Density-Based Spatial Clustering of Applications with Noise (DBSCAN) and a Bayesian
Gaussian Mixture Model (BGMM) within an integrated clustering framework. The results
showed that DBSCAN identified a simpler mainshock–aftershock sequence, while BGMM
produced a more complex foreshock–mainshock–aftershock sequence. The authors emphasized
that different clustering algorithms can produce different interpretations and that single clustering
methods should be applied with caution.
This study is relevant to QuakeStrike PH because it directly supports the need to choose
and justify the clustering method used for mainshock–aftershock sequence detection. It shows
that clustering results may vary depending on the algorithm, which is important when using
methods such as Gardner-Knopoff, DBSCAN, or other spatial-temporal clustering approaches. In
relation to the proposed system, this supports using a simple and explainable method for the
capstone stage, while acknowledging that future work may compare multiple clustering
approaches to improve reliability.
Sawi, Kita, and Bürgmann (2024) conducted a machine-learning-based relocation
analysis of the 2019 Cotabato and Davao del Sur earthquake sequence in the Philippines. The
study used the deep-neural-network phase picker PhaseNet to obtain seismic phases from
26

earthquake waveform data within 200 kilometers of the events over an 80-day period. These
phases were associated and located using REAL, then refined using VELEST and hypoDD. The
method produced an earthquake catalog with approximately 5,000 earthquakes, exceeding the
roughly 3,000 events in the original DOST-PHIVOLCS catalog that relied on manually selected
phases.
Although this study did not forecast aftershocks directly, it provides important national
evidence that machine learning can improve earthquake sequence analysis in the Philippine
setting. It also highlights a local research gap: existing Philippine machine learning–related work
has focused more on earthquake detection, phase picking, relocation, and catalog improvement
than on public-facing aftershock forecasting. In relation to QuakeStrike PH, this supports the
need for a localized system that builds from PHIVOLCS earthquake data and applies machine
learning toward aftershock sequence detection and likelihood estimation.
Devi and Pasari (2025) implemented an area-based earthquake nowcasting approach for
the Philippine archipelago. The study statistically computed the current level of seismic hazard in
26 densely populated cities across the Philippines. Although the study did not use Random
Forest or Gradient Boosting regression, it remains relevant because it applies a quantitative,
area-based earthquake occurrence model to the Philippine setting. The study also emphasized
that earthquakes caused by unmapped faults indicate the need for area-based hazard evaluation
approaches.
This is relevant to QuakeStrike PH because it demonstrates that Philippine earthquake
data can be analyzed through statistical modeling to estimate seismic hazard levels. In relation to
the proposed system, this supports the use of Philippine earthquake catalog data for localized
seismic interpretation. However, since the study focuses on nowcasting rather than aftershock
27

forecasting, it also shows that there remains room for a system like QuakeStrike PH, which
focuses specifically on aftershock sequence detection and short-term aftershock likelihood
estimation.
The reviewed studies demonstrate that machine learning is increasingly being applied to
earthquake and aftershock-related problems, including aftershock ground-motion forecasting,
earthquake occurrence forecasting, declustering, strong aftershock classification, and earthquake
catalog improvement. Yu et al. (2025) supports the use of machine learning with
mainshock-derived features, while Dascher-Cousineau et al. (2023) reinforces the argument that
machine learning can complement traditional statistical forecasting models such as ETAS. Perry
and Bendick (2024) supports the need for declustering before forecasting, and Niteesh et al.
(2024) shows the feasibility of applying simple regression models such as Random Forest,
Decision Tree, and Linear Regression to earthquake-related prediction tasks. Gentili et al. (2025)
demonstrates that strong aftershock classification can be performed within short windows such
as the first six hours to the first day after a mainshock, while Zhao et al. (2021) emphasizes that
carefully selected features may matter more than model complexity in aftershock spatial
prediction. Liu et al. (2024) supports the use of interpretable, map-based machine learning
approaches that align well with QuakeStrike PH's interactive visualization goals.
Studies on Asian earthquake sequences further reinforce the importance of catalog
quality and clustering choice. Liao et al. (2025) and Kuo-Chen et al. (2025) show that
deep-learning-empowered cataloging can detect more aftershock activity than traditional
methods, supporting the need for clean and complete catalog data before sequence analysis. Wan
and Heron (2026) highlight that different clustering algorithms can produce different
mainshock–aftershock interpretations, which justifies a careful and explainable choice of
28

clustering method for the capstone stage. In the Philippine context, Sawi et al. (2024) provides
national evidence that machine learning can improve earthquake sequence analysis, while Devi
and Pasari (2025) shows that quantitative seismic hazard modeling has already been applied to
the Philippines through nowcasting. Together, these local studies indicate that existing Philippine
machine learning–related work has focused mainly on detection, relocation, cataloging, and
area-based hazard estimation, and that public-facing aftershock likelihood forecasting based on
PHIVOLCS data remains an open area where QuakeStrike PH can contribute.
2.1.5 Web-Based Earthquake Information and Visualization Systems
The development of web-based earthquake information systems has been driven by the
need to make seismic data easier for the public to understand. Technical bulletins and scientific
reports are useful for researchers and technical agencies, but they are not always easy for
ordinary users to interpret, especially after a recent earthquake. In situations where people want
to know whether an event may still be followed by other earthquakes, raw data alone may not be
enough. QuakeStrike PH is being developed within this context. By reviewing existing
earthquake information and visualization systems, it becomes clearer what features are already
available and what gap the proposed system can address.
One of the most established international examples is the USGS Latest Earthquakes Map
and List. The platform presents earthquake events in real time through a map-and-list interface,
allowing users to search and filter seismic events. It is also designed for both desktop and mobile
use, which makes earthquake information easier to access for a wider range of users (U.S.
Geological Survey, 2019). This system is relevant to QuakeStrike PH because both systems aim
to make earthquake catalog data more usable for people who are not seismologists. The USGS
29

platform has already shown how earthquake records can be presented clearly and at a large scale.
However, within this particular platform, the focus remains mainly on reporting where and when
earthquakes occurred. It does not provide simplified aftershock likelihood indicators or a
public-facing interpretation of what a sequence of events may suggest after a major earthquake.
Another related global system is the IRIS Earthquake Browser, which was evaluated by
Sumy, Welti, and Hubenthal (2020). Unlike the USGS platform, IRIS is more oriented toward
education and data exploration. It allows users to search a large earthquake database and filter
events according to magnitude, depth, time, and location. The study noted that spatiotemporal
visualization helps users observe earthquake patterns more clearly over time. This is important
for QuakeStrike PH because the proposed system also depends on map-based and time-based
display to communicate earthquake activity. The difference, however, is in the purpose of the
system. IRIS helps users explore and learn from earthquake data, while QuakeStrike PH is
intended to help users interpret recent seismic activity in a more practical and public-oriented
way, especially when aftershocks are possible.
In the Asian region, some systems have gone beyond basic earthquake mapping and have
started to include more interpretive functions. Liu et al. (2023) documented a real-time automatic
aftershock forecasting system developed in China. The system uses seismic data, geological
information, expert rules, and historical analogies to produce short-term aftershock forecasts
within minutes after a significant earthquake. It can estimate the type of earthquake sequence and
the possible magnitude range of future events, with outputs intended for scientists and
government agencies. Among the systems reviewed, this is one of the closest to QuakeStrike PH
in terms of function because it involves automated aftershock analysis and rapid reporting. The
main difference is the intended user. The Chinese system is built mainly for technical and
30

government users, while QuakeStrike PH aims to translate probability-based outputs into Low,
Medium, and High indicators that are easier for non-expert users to understand.
Yang, Mittal, and Wu (2023) also examined Taiwan’s P-Alert Earthquake Early Warning
System during the 2022 Chishang earthquake. The system uses a dense network of low-cost
sensors to generate shake maps shortly after a major earthquake. In their study, the areas
identified by the shake maps matched well with locations where damage was observed. P-Alert
does not focus on aftershock likelihood forecasting, since its main purpose is earthquake early
warning and shake mapping. Still, the system is useful in relation to QuakeStrike PH because it
shows the value of rapid and accessible visual outputs during earthquake events. Even when a
system does not forecast aftershocks, timely visualization can help users better understand the
situation and support awareness during post-earthquake conditions.
In the Philippine context, GeoRiskPH is one of the major efforts to make hazard
information more accessible through geospatial and web-based systems. Cahulogan et al. (2018)
described GeoRiskPH as a national project that organizes government hazard data and develops
GIS and IT infrastructure for web and mobile applications. This is relevant to QuakeStrike PH
because both systems rely on geospatial data and digital platforms to present hazard-related
information. However, GeoRiskPH covers a wider range of natural hazards, while QuakeStrike
PH is more specific to earthquake events, aftershock sequence detection, and aftershock
likelihood communication.
One of the most visible outputs of GeoRiskPH is HazardHunterPH. It is a public-facing
web platform that allows users to check the hazard exposure of a selected location, including
seismic, volcanic, and hydrometeorological hazards (GeoRiskPH, 2019). It also includes an
earthquake events monitoring feature with filters for date range, magnitude, and time period, all
31

displayed through a map interface (GeoRiskPH, n.d.). This feature is directly related to
QuakeStrike PH because it shows that earthquake event visualization and filtering are already
possible in a Philippine government platform. However, the system mainly shows where and
when earthquakes happened. It does not interpret whether a sequence of seismic events may
indicate continuing aftershock activity, nor does it communicate aftershock likelihood through
simplified categories. This is the specific gap that QuakeStrike PH intends to address.
Overall, the reviewed systems show that web-based earthquake information platforms are
already useful for presenting seismic events through maps, lists, filters, and visual tools.
International platforms such as the USGS Latest Earthquakes Map and the IRIS Earthquake
Browser demonstrate how earthquake catalog data can be made more accessible to users.
Regional systems, such as China’s automatic aftershock forecasting system and Taiwan’s P-Alert
system, also show the value of rapid processing and visual outputs during earthquake events. In
the Philippines, GeoRiskPH and HazardHunterPH show that public-facing hazard platforms can
work within the local setting using government-generated data. However, existing Philippine
platforms mainly present earthquake and hazard information rather than detecting possible
aftershock sequences and communicating aftershock likelihood in a simplified way. This gap
supports the development of QuakeStrike PH as a web-based system that focuses not only on
showing earthquake events, but also on helping users interpret possible aftershock activity.
32

2.2 Gaps Bridged by the Study
Despite the numerous studies on earthquake monitoring, aftershock forecasting, machine
learning-based seismic analysis, and web-based earthquake information systems, a significant
gap remains in the development of a localized, public-oriented platform that combines aftershock
sequence detection, probabilistic aftershock likelihood estimation, and simplified risk
communication using Philippine earthquake catalog data. The main focus of current systems like
PHIVOLCS, GeoRiskPH, and global platforms like USGS is on earthquake reporting, hazard
visualization, or technical forecasting outputs that may still be challenging for non-expert users
to understand. Additionally, there is little study on applying machine learning and forecasting
techniques to Philippine seismic features and public-facing aftershock interpretation because the
majority of these studies use foreign datasets and tectonic settings.
This study bridges this gap by developing a system that detects possible
mainshock-aftershock sequences using PHIVOLCS earthquake catalog data and generates
probability-based aftershock likelihood indicators presented in a simplified and user-friendly
format. QuakeStrike PH seeks to enhance public comprehension of aftershock activity and
facilitate better decision-making in post-earthquake scenarios by integrating spatiotemporal
analysis, machine learning-supported forecasting techniques, interactive visualization tools, and
intuitive likelihood categories.
33

2.3 Concept of the Study
Figure 1. Conceptual Framework
The complete process of QuakeStrike PH: A Web-Based Aftershock Likelihood
Forecasting System Using PHIVOLCS Earthquake Data is depicted in the conceptual framework
(see Figure 1). It describes how data processing, sequence identification, machine learning
forecasting, and web-based visualization are used to convert raw seismic data from official
earthquake catalog records into processed, analyzed, and publicly interpretable aftershock
likelihood outputs.
The PHIVOLCS earthquake catalog data, which is the system’s main input, opens the
first section of the diagram. The date, time, latitude, longitude, depth, and magnitude of
earthquake events are among the crucial seismic parameters included in this collection. The
temporal, geographical, and magnitude-related data required to examine earthquake behavior and
determine potential correlations between mainshocks and aftershocks are provided by these
variables.
34

2.4 Definition of Terms
Several terminologies used in this study were conceptually and operationally defined to
facilitate a clear understanding of the content of the study.
Aftershock. An aftershock is an earthquake that follows the largest shock of an
earthquake sequence, usually occurring near the mainshock area and possibly continuing for
weeks, months, or years (U.S. Geological Survey [USGS], n.d.). In this study, aftershock refers
to a later earthquake event identified from PHIVOLCS earthquake catalog data as part of a
possible mainshock-aftershock sequence.
Aftershock Likelihood. Aftershock likelihood refers to the probability that one or more
aftershocks may occur within a given time period and magnitude range after an earthquake event
(USGS, n.d.). In this study, aftershock likelihood refers to the percentage-based output generated
by QuakeStrike PH indicating the chance of at least one aftershock occurring within 24 hours.
Earthquake. An earthquake is the sudden release of energy in the Earth’s crust that
produces seismic waves and causes ground shaking (PHIVOLCS, n.d.). In this study, earthquake
refers to a recorded seismic event from PHIVOLCS data containing date-time, latitude,
longitude, depth, and magnitude.
Epicenter. The epicenter is the point on the Earth’s surface directly above the
underground point where an earthquake starts (USGS, n.d.). In this study, epicenter refers to the
latitude and longitude location of an earthquake event used to estimate possible aftershock
distance ranges.
Machine Learning. Machine learning is a computational approach that enables systems
to learn patterns from data and make predictions or classifications based on those learned
patterns (Hardebeck et al., 2023). In this study, machine learning refers to the model used to
35

estimate percentage-based aftershock likelihood, possible distance range, and possible maximum
aftershock magnitude from historical earthquake data.
Magnitude. Magnitude is a numerical measure of the size or energy released by an
earthquake (USGS, n.d.). In this study, magnitude refers to the PHIVOLCS-recorded earthquake
magnitude used as an input feature for clustering and aftershock likelihood forecasting.
Mainshock. A mainshock is the largest earthquake in an earthquake sequence and is
commonly followed by smaller earthquakes called aftershocks (USGS, n.d.). In this study,
mainshock refers to the event identified through clustering as the largest earthquake within a
mainshock-aftershock family or sequence.
P Waves. P waves, or primary waves, are body waves that arrive first during an
earthquake and travel through the Earth by compressing and expanding material in the direction
of wave movement (IRIS, n.d.). In this study, P waves are treated as a background earthquake
concept and are not directly used as a forecasting input in the QuakeStrike PH system.
PHIVOLCS Earthquake Data. PHIVOLCS earthquake data refers to earthquake
information released by the Philippine Institute of Volcanology and Seismology, the official
agency responsible for monitoring earthquake activity in the Philippines (PHIVOLCS, n.d.). In
this study, PHIVOLCS earthquake data refers to the earthquake catalog records used by
QuakeStrike PH, particularly date-time, latitude, longitude, depth, and magnitude.
Probabilistic Forecasting. Probabilistic forecasting is a forecasting approach that
expresses future outcomes as probabilities rather than exact predictions (USGS, n.d.). In this
study, probabilistic forecasting refers to estimating the likelihood of aftershock occurrence within
24 hours instead of predicting the exact time, location, or magnitude of an earthquake.
36

S Waves. S waves, or secondary waves, are body waves that move the ground
perpendicular to the direction of travel and generally arrive after P waves (IRIS, n.d.). In this
study, S waves are included only as a supporting earthquake concept and are not directly
processed by the system.
Seismic Waves. Seismic waves are waves of energy generated by earthquakes that travel
through the Earth or along its surface (IRIS, n.d.). In this study, seismic waves explain the basic
physical process of earthquakes, but QuakeStrike PH uses earthquake catalog records rather than
waveform data.
Spatiotemporal Analysis. Spatiotemporal analysis refers to the examination of patterns
across both space and time, which is important in identifying earthquake clustering behavior
(Zaliapin & Ben-Zion, 2013). In this study, spatiotemporal analysis refers to analyzing
earthquake location and occurrence time to help identify historical mainshock-aftershock
relationships.
Surface Waves. Surface waves are seismic waves that travel along the Earth’s surface
and include Love and Rayleigh waves (IRIS, n.d.). In this study, surface waves are treated as a
basic earthquake term and are not directly used in the machine learning or clustering process.
Zaliapin Ben-Zion (2013) Nearest-Neighbor Cluster Identification Algorithm. The
Zaliapin and Ben-Zion nearest-neighbor method identifies earthquake clusters using distances in
space, time, and magnitude domains (Zaliapin & Ben-Zion, 2013). In this study, Zaliapin
nearest-neighbor clustering refers to the preprocessing method used to identify historical
mainshock-aftershock relationships before training or applying the aftershock likelihood model.
37

3 MATERIALS AND METHODS
This chapter presents the materials and methods used in the development of the system. It
covers the hardware, software, data sources, development tools, and system components required
to create and execute the proposed system. Additionally, it describes the steps taken to gather and
process earthquake data, apply the Zaliapin nearest-neighbor clustering method, prepare the
dataset for machine learning, produce outputs on percentage-based aftershock likelihood, and
create the web-based interface. This chapter also explains the evaluation process and system
development technique used to evaluate the system’s usability, acceptability, and functionality.
3.1 Materials
In this section, the study discusses the materials used in the documentation of the study
and the development of the proposed system.
3.1.1 Software
The software resources used in the development of QuakeStrike PH were selected based
on the system’s requirements for web development, data processing, database management,
background task handling, machine learning integration, deployment, and collaboration. These
tools supported the development of the web-based earthquake monitoring interface, the
automated PHIVOLCS data collection process, the aftershock likelihood processing workflow,
and the storage and retrieval of earthquake and prediction records.
Table 1. Software Requirement
Software / Tool Versions
Visual Studio Code Latest version
Python 3.14.4
JavaScript / TypeScript Latest stable version

React 19.2.5
Next.js 16.2.4
C++ Latest stable version
Zaliapin Cluster Identification Algorithm Not applicable
Supabase PostgreSQL Cloud-managed
Supabase JS Client Latest stable version
Celery Latest stable version
Celery Beat Latest stable version
Upstash Redis Cloud-managed
Docker Compose 5.1.3
Vercel Cloud-managed
Oracle Cloud Always Free VM Cloud-managed
Git 2.54.0
Github Cloud-managed
Figma Cloud-managed
Google Stitch Cloud-managed
Google Chrome Latest version
Windows Operating System Windows 10 or higher
The development team used Windows 10 or higher as the recommended operating system
to ensure compatibility with the selected tools and to avoid security risks associated with
unsupported operating system versions. Visual Studio Code served as the primary development
environment because it supports web development, Python scripting, Git integration, and project
configuration management. Google Chrome was used for testing, debugging, and viewing the
web application during development.
For frontend development, React and Next.js were used to build the web-based dashboard
that displays earthquake events, selected event details, filters, forecast history, and
percentage-based aftershock likelihood outputs. JavaScript and TypeScript supported the
frontend logic and the connection between the web application and Supabase. Python was used
for backend processing tasks, including the PHIVOLCS scraper, Celery background tasks, and
machine learning worker. C++ was used to support the clustering process for the earthquake
39

dataset, while the Zaliapin Cluster Identification Algorithm served as the method for identifying
foreshock, mainshock, and aftershock relationships.
For data storage and retrieval, Supabase PostgreSQL was used as the main database for
earthquake records, prediction results, scraper logs, and processing-related data. The Supabase
JS Client allowed the frontend to securely read public earthquake and prediction records from
Supabase using Row Level Security policies. Celery, Celery Beat, and Upstash Redis supported
the automated background workflow of the system, including scheduled PHIVOLCS scraping,
queued prediction tasks, scraper locks, and temporary coordination data.
For deployment, Docker Compose was used to package and run backend services such as
the scraper, scheduler, and machine learning worker on the Oracle Cloud Always Free VM.
Vercel was used to host and deploy the frontend web application. For collaboration and source
code management, Git and GitHub were used to track changes, manage project versions, and
share the project repository among the development team. Lastly, Figma and Google Stitch were
used during the UI/UX design process to prepare the interface layout, dashboard screens, and
visual presentation of earthquake and aftershock likelihood information.
3.1.2 Hardware
Table 2. Hardware Specifications
Hardware Specifications
Laptop Acer NITRO 5, Windows 11, Ryzen 5, GTX
1650, 8GB RAM, 237 GB SSD
Laptop Asus Vivobook, Windows 11, Intel Core i5
Evo, 8GB RAM, 256GB SSD
Laptop Asus TUF F15, Windows 11, Intel Core i5,
RTX 2050, 8GB RAM
Android Mobile Phone Realme Note 70, Unisoc T7250, 4G, 12nm,
4GB RAM, 64GB Storage
40

The laptops served as the main development machines for building the frontend interface,
writing and testing backend scripts, managing project files, and running local development tools.
These machines were also used for coding, version control, browser testing, and preparing
project documentation. Their specifications were sufficient for web development, Python-based
data processing, clustering-related implementation, and system testing.
The Android mobile phone was used as a testing device to check the responsiveness and
usability of the web-based interface on a mobile screen. Since QuakeStrike PH is designed as a
web-based application, testing on a mobile device helped ensure that users could still access
earthquake event information, filters, maps, and aftershock likelihood outputs through smaller
screens.
3.2 Software Methodology
The Agile methodology was adopted as the development methodology for this project
because the system requirements are clear in terms of core functions, such as PHIVOLCS
earthquake data collection, aftershock likelihood estimation, and map-based data presentation,
but the exact interface design and data presentation approach may still improve through testing
and feedback. The system's direction was validated through consultations with the Chief of the
Seismological Prediction Division (SOEPD) and our programming adviser Dr. Aries Ordonez.
While they provided critical insights into the practical application of earthquake data, the specific
presentation of results was left to the developers' discretion. The Agile methodology is suitable
for QuakeStrike PH because the project involves multiple interconnected system components
and model development activities, including the Vercel web frontend, Supabase PostgreSQL
41

database, Oracle Cloud backend workers, scheduled scraper, Redis queue, clustering process,
machine learning training phase, and machine learning-based aftershock likelihood estimation
Celery worker. These parts require continuous testing, evaluation, and refinement. Through
Agile, the researchers can incrementally develop the system, validate each module in stages, and
improve both the application and the likelihood estimation model throughout the development
process. It also aligns with the project’s focus on usability, the clear presentation of
percentage-based aftershock likelihood indicators, and the evaluation of the system through user
experience and output accuracy. The methodology is carried out through short development
sprints, with each cycle focusing on the implementation, testing, and refinement of specific
modules. These include automating the PHIVOLCS scraper, maintaining data integrity within
the Supabase database, developing the clustering process, training the machine learning model,
and integrating the prediction worker for generating percentage-based aftershock likelihood
estimates. For the analytical component, the team implements Zaliapin-based clustering using
C++ to efficiently detect and organize potential aftershock sequences, while Python is used to
generate analytical graphs and support model development. The React frontend is then used to
present earthquake events and likelihood outputs through a map-based interface.
While Agile methodology offers flexibility and allows the team to improve the system
through continuous testing and feedback, it also carries the risk of scope changes and unclear
priorities if revisions are not properly controlled. This may affect QuakeStrike PH because the
system includes several interconnected components, such as PHIVOLCS data scraping,
Supabase database storage, data clustering, machine learning model training, aftershock
likelihood processing, and web-based visualization. To mitigate this, the team will maintain a
prioritized backlog, define clear sprint goals, document approved requirements, and limit major
42

changes to scheduled review points. This ensures that improvements can still be made without
delaying essential features such as earthquake data collection, duplicate prevention,
percentage-based likelihood generation, and map-based result presentation.
3.2.1 Requirements Planning
The team employed client interviews, observation of existing processes, document /
records review, feedback to gather and document system requirements. The team employed
document review, formal correspondence, client interview, and consultation to gather and
document the system requirements. The team leader established contact with PHIVOLCS, while
the team actively consulted with one another to identify the needed data, system functions, and
technical direction of the project. The team also drafted and submitted data request letters and an
interview letter to formally request access to earthquake-related data and consultation. A Zoom
meeting with the PHIVOLCS-SOEPD Chief was conducted for data consultation, where the
team learned how the earthquake data can and should be used for the system, while the
presentation of the data was left to the developers’ discretion. The gathered requirements were
organized into a Software Requirements Specification (SRS) and development backlog,
consisting of functional requirements grouped into major modules such as data collection, data
storage, data clustering using Zaliapin nearest-neighbor cluster identification method, machine
learning model training, aftershock percentage-based likelihood generation, map visualization,
event filtering, and system evaluation.
A total of 10 functional requirements were identified, organized into the following
categories: Earthquake Data Collection and Scraping; Earthquake Event Storage and Duplicate
Prevention; Aftershock Likelihood Estimation; Web Dashboard and Data Visualization;
43

Earthquake Event and Forecast Search Filtering; Database Security and Row Level Security;
Background Task Processing and Queue Management; System Monitoring and Error Logging;
User Access and Data Viewing Permissions.
Figure 2. Interview with PHIVOLCS-SOEPD
3.2.2 User Design
The system will follow a web-based, cloud-integrated architecture consisting of a
Vercel-hosted front-end, an Oracle Cloud backend processing layer, an Upstash Redis
queue/cache layer, and a Supabase PostgreSQL database layer. The user interface will be
designed using Figma, beginning with low-fidelity wireframes that will map each screen to the
requirements identified in Section 3.2.1. The team will produce wireframes, mockups, and
interactive prototypes for the main screens, including the earthquake map dashboard, searchable
event and forecast list, filter controls for time, magnitude, location, and the aftershock likelihood
display using percentage-based indicators. The designs will focus on presenting PHIVOLCS
44

earthquake data in a clear and understandable format, since PHIVOLCS provided guidance on
how the data can and should be used but left the presentation and interface design decisions to
the development team. The prototypes will undergo a comprehensive review process involving
internal team consultations, external user testing, and formal feedback from both the project’s
programming advisers and the PHIVOLCS-SOEPD. This collaborative evaluation ensures the
layout, navigation, visual indicators, and user flow remain consistent with the technical
requirements and scientific standards established during the planning phase. Unlike earlier
iterations, the UI design will be specifically validated by these key stakeholders to ensure the
percentage-based likelihood indicators and map visualizations are both intuitive and reliable.
Furthermore, final user satisfaction and the overall acceptability of the interface will be measured
during the User Acceptance Testing (UAT) phase using a 5-point Likert scale.
The front-end will retrieve public earthquake events and aftershock prediction results
directly from Supabase using the Supabase JS Client and Row Level Security policies, while the
backend will run on an Oracle Cloud Always Free VM using Docker/Docker Compose to
operate the PHIVOLCS scraper, Celery Beat scheduler, Celery worker, and Python machine
learning worker. Every 15 minutes, the scraper will collect earthquake data from PHIVOLCS,
normalize and validate the records, prevent duplicates through database-level constraints, and
store new earthquake events in Supabase; once a new event is saved, a prediction job will be
queued in Upstash Redis and processed by the Celery ML worker using the trained aftershock
likelihood model. The generated likelihood result will then be saved back to Supabase, where the
web application will display updated earthquake information and Percentage-based likelihood
indicators. The database will use a relational schema composed of recommended tables such as
earthquake_events, aftershock_predictions, scraper_runs, and processing_jobs, with relationships
45

defined through foreign key constraints, particularly between earthquake records and their
corresponding prediction results.
Figure 3. Dashboard
Figure 4. Forecast History
46

Figure 5. Forecast View
Figure 6. Forecast Detailed View
47

3.3 Evaluation Procedure
The evaluation of QuakeStrike PH will be conducted to determine whether the
implemented features meet the functional requirements of the system and to assess its functional
correctness, usability, reliability, performance, data accuracy, clarity of data presentation,
security, compatibility, and overall usefulness. The evaluation will be performed throughout the
development process through different testing activities, including unit testing, integration
testing, system testing, performance testing, security testing, usability testing, sprint reviews, and
User Acceptance Testing (UAT).
Unit testing will be conducted during development to check individual system
components such as the PHIVOLCS scraper, duplicate detection, database operations, and
prediction logic. Integration testing will be performed during each sprint to verify whether the
frontend, Supabase PostgreSQL database, Upstash Redis queue, Oracle Cloud background
workers, and machine learning model work correctly together. System testing will be conducted
to evaluate the complete workflow of the application, from earthquake data collection to
aftershock likelihood output display. Performance testing will assess the system’s response time
and ability to handle scheduled data processing, while security testing will check access control
and data protection mechanisms. Usability testing will determine whether the system is easy to
navigate and whether the presented earthquake and aftershock likelihood information is
understandable to users.
User Acceptance Testing will be conducted during the dedicated testing phase after the
main features have been implemented. The UAT will use scenario-based tasks, where selected
respondents will test the system by viewing earthquake records, applying filters, exploring the
map interface, checking forecast history, and interpreting the aftershock likelihood indicators.
48

After completing the tasks, respondents will answer a questionnaire using a 5-point Likert scale.
The questionnaire will measure usability, reliability, performance, accuracy, clarity of data
presentation, and overall usefulness. The system will be considered acceptable if it obtains a
minimum average rating of 4.00 out of 5.00 overall and at least 4.00 in each major evaluation
area, with no unresolved critical errors before deployment.
Table 3. Likert Scale
Range Meaning Description
5 Strongly Agree The system fully meets the expected
criteria and is highly usable, reliable,
accurate, clear, and useful.
4 Agree The system meets the expected criteria and
is usable, reliable, accurate, clear, and
useful.
3 Neutral The system moderately meets the expected
criteria but may still require improvements
in some areas.
2 Disagree The system slightly fails to meet the
expected criteria and shows noticeable
issues in usability, reliability, accuracy,
clarity, or usefulness.
1 Strongly Disagree The system does not meet the expected
criteria and is not usable, reliable, accurate,
clear, or useful.
The acceptance criteria for deployment will be based on both technical testing and user
evaluation results. The system must be able to collect earthquake data from PHIVOLCS at
scheduled intervals, detect new events, prevent duplicate records, and store complete earthquake
information in the database. The backend processing workflow, database connection, machine
learning model, and frontend display must also function correctly, securely, and within
49

acceptable response times. In addition, the system must present updated and understandable
earthquake records, map information, filters, forecast history, and aftershock likelihood outputs
across supported devices. Final deployment may proceed only when the system passes the
required tests, achieves the target UAT rating, and has no unresolved critical errors.
50

REFERENCES
Batac, R. C. (2015). Statistical properties of the immediate aftershocks of the 15 October 2013
magnitude 7.1 earthquake in Bohol, Philippines. Acta Geophysica, 64(1), 15–25.
https://doi.org/10.1515/acgeo-2015-0054
Bi, J., Song, C., & Cao, F. (2024). Declustering characteristics of the North China Plain seismic
belt and its effect on probabilistic seismic hazard analysis. Scientific Reports, 14(1),
Article 22170. https://doi.org/10.1038/s41598-024-73815-9
Cahulogan, M. T., Santos, E. P., Sulit, R. G., Ragadio, A. C., Nadua, J. H., Montano, M. P. L.,
Dolanas, R. M., Tabuzo, J. H. B., Favis, C. A. M., Pascual, P. D. E., Mahor, M. A. P.,
Aquino, Y. P. M., Balasabas, A. J. H., Damasco, J. C., Nadua, J. M. H., Balboa, J. A.,
Ramirez, M. J., Hugo, M. K. D., Gatdula, C. J. T., & Solidum, R. U., Jr. (2018).
Geospatial information, systems and technologies for efficient hazard and risk
assessments. Geological Convention of the Geological Society of the Philippines.
https://doi.org/10.13140/RG.2.2.32187.44322
Centre for Research on the Epidemiology of Disasters. (2024). 2023 disasters in numbers: A
significant year of disaster impact. ReliefWeb.
https://reliefweb.int/report/world/2023-disasters-numbers
Dascher-Cousineau, K., Shchur, O., Brodsky, E. E., & Günnemann, S. (2023). Using deep
learning for flexible and scalable earthquake forecasting. Geophysical Research Letters,
50(17). https://doi.org/10.1029/2023GL103909
51

Department of Science and Technology–Science and Technology Information Institute. (2018,
January). DOST-PHIVOLCS launches earthquake model atlas. DOST Digest, 11(1), 1–2.
https://stii.dost.gov.ph/images/jdownloads/pdf_files/digest/2018/Digest_JANUARY2018.
pdf
Devi, S., & Pasari, S. (2025). Nowcasting earthquakes in the Philippines archipelago. Journal of
Seismology, 29(2), 505–524. https://doi.org/10.1007/s10950-024-10277-6
EarthScope Consortium. (n.d.). Seismic wave motions—4 waves animated. IRIS.
https://www.iris.edu/hq/inclass/animation/seismic_wave_motions4_waves_animated
Galasso, C., & Opabola, E. A. (2024). The 2023 Kahramanmaraş earthquake sequence: Finding a
path to a more resilient, sustainable, and equitable society. Communications Engineering,
3, Article 24. https://doi.org/10.1038/s44172-024-00170-y
Garfin, D. R., & Silver, R. C. (2023). Addressing mental health aftershocks from the
Turkey–Syria earthquake: A call to action. Nature Mental Health, 1, 238–239.
https://doi.org/10.1038/s44220-023-00052-w
Gentili, S., Chiappetta, G., Petrillo, G., Brondi, P., & Zhuang, J. (2025). Forecasting strong
subsequent earthquakes in Japan using an improved version of NESTORE machine
learning algorithm. Geoscience Frontiers, 16(3), Article 102016.
https://doi.org/10.1016/j.gsf.2025.102016
GeoRiskPH. (2019). HazardHunterPH: Hazard assessment at your fingertips [Web application].
Department of Science and Technology–Philippine Institute of Volcanology and
Seismology. https://hazardhunter.georisk.gov.ph/
52

GeoRiskPH. (n.d.). Earthquake events monitoring [Web application]. Department of Science and
Technology–Philippine Institute of Volcanology and Seismology.
https://hazardhunter.georisk.gov.ph/monitoring/earthquake
Hardebeck, J. L., Llenos, A. L., Michael, A. J., Page, M. T., Schneider, M., & van der Elst, N. J.
(2024). Aftershock forecasting. Annual Review of Earth and Planetary Sciences, 52,
61–84. https://doi.org/10.1146/annurev-earth-040522-102129
IBM. (n.d.). What is machine learning? https://www.ibm.com/think/topics/machine-learning
Japan Meteorological Agency. (n.d.). Aftershock information.
https://www.jma.go.jp/jma/en/Activities/aftershock.html
Jordan, T. H., Marzocchi, W., Michael, A. J., & Gerstenberger, M. C. (2014). Operational
earthquake forecasting can enhance earthquake preparedness. Seismological Research
Letters, 85(5), 955–959. https://doi.org/10.1785/0220140143
Kuo-Chen, H., Sun, W., Kan, L., Pan, S., Yen, I., Liang, S., Guan, Z., Liu, Y., Chen, W., &
Brown, D. (2025). Real-time earthquake monitoring with deep learning: A case study of
the 2025 ML 6.4 Dapu earthquake and its fault system in southwestern Taiwan. The
Seismic Record, 5(3), 320–329. https://doi.org/10.1785/0320250023
Liao, W., Lee, E., Rau, R., Chen, D., Wen, S., Ching, K., & Liang, W. (2025). Fast report:
Seismogenic structure of the 2025 M6.4 Dapu earthquake sequence in western Taiwan
revealed by a deep-learning-empowered earthquake catalog. Terrestrial, Atmospheric and
Oceanic Sciences, 36(1). https://doi.org/10.1007/s44195-025-00093-x
53

Liu, B., Wen, H., Di, M., Huang, J., Liao, M., Yu, J., & Xiang, Y. (2024). Mapping and
interpretability of aftershock hazards using hybrid machine learning algorithms. Journal
of Rock Mechanics and Geotechnical Engineering, 17(8), 4908–4932.
https://doi.org/10.1016/j.jrmge.2024.09.015
Liu, Z., Jiang, H., Li, S., Li, M., Liu, J., & Zhang, J. (2023). Implementation and verification of a
real-time system for automatic aftershock forecasting in China. Earth Science
Informatics, 16, 1891–1907. https://doi.org/10.1007/s12145-023-00960-6
National Disaster Risk Reduction and Management Council. (2020, September 10). NDRRMC
update: SitRep No. 10 re magnitude 6.6 earthquake in Cataingan, Masbate. ReliefWeb.
https://reliefweb.int/report/philippines/ndrrmc-update-sitrep-no-10-re-magnitude-66-earth
quake-cataingan-masbate-10
Niteesh, K. R., Pooja, T. S., Pushpa, T. S., Lakshminarayana, P., & Girish, K. (2024).
Comparative analysis of machine learning models for earthquake prediction using large
textual datasets. In Lecture Notes in Civil Engineering (pp. 237–244). Springer.
https://doi.org/10.1007/978-981-99-9610-0_21
Omi, T., Ogata, Y., Shiomi, K., Enescu, B., Sawazaki, K., & Aihara, K. (2018). Implementation
of a real-time system for automatic aftershock forecasting in Japan. Seismological
Research Letters, 90(1), 242–250. https://doi.org/10.1785/0220180213
Peñarubia, H. C., Johnson, K. L., Styron, R. H., Bacolcol, T. C., Sevilla, W. I. G., Perez, J. S.,
Bonita, J. D., Narag, I. C., Solidum, R. U., Jr., Pagani, M. M., & Allen, T. I. (2020).
54

Probabilistic seismic hazard analysis model for the Philippines. Earthquake Spectra,
36(1_suppl), 44–68. https://doi.org/10.1177/8755293019900521
Perry, M., & Bendick, R. (2024). A comparative analysis of five commonly implemented
declustering algorithms. Journal of Seismology, 28(3), 829–842.
https://doi.org/10.1007/s10950-024-10221-8
Philippine Institute of Volcanology and Seismology. (n.d.). Earthquake monitoring system.
Department of Science and Technology.
https://www.phivolcs.dost.gov.ph/earthquake-monitoring-system/
Philippine Institute of Volcanology and Seismology. (n.d.). Introduction to earthquake.
Department of Science and Technology.
https://www.phivolcs.dost.gov.ph/introduction-to-earthquake/
Philippine Institute of Volcanology and Seismology. (2020). Masbate earthquake information and
updates. Department of Science and Technology. https://www.phivolcs.dost.gov.ph
Sawi, P., Kita, S., & Bürgmann, R. (2024). Machine-learning-based relocation analysis:
Revealing the spatiotemporal changes in the 2019 Cotabato and Davao del Sur
earthquakes. EGU General Assembly 2024.
https://doi.org/10.5194/egusphere-egu24-3482
Schneider, M., McDowell, M., Guttorp, P., Steel, E. A., & Fleischhut, N. (2022). Effective
uncertainty visualization for aftershock forecast maps. Natural Hazards and Earth System
Sciences, 22(4), 1499–1518. https://doi.org/10.5194/nhess-22-1499-2022
55

Sedghizadeh, M., & Shcherbakov, R. (2022). The analysis of the aftershock sequences of the
recent mainshocks in Alaska. Applied Sciences, 12(4), Article 1809.
https://doi.org/10.3390/app12041809
Shu, M., & Song, R. (2025). Prediction of aftershock characteristics based on earthquake
mainshock. SSRN Electronic Journal. https://doi.org/10.2139/ssrn.5075517
Sumy, D. F., Welti, R., & Hubenthal, M. (2020). Applications and evaluation of the IRIS
Earthquake Browser: A web-based tool that enables multidimensional earthquake
visualization. Seismological Research Letters, 91(5), 2922–2935.
https://doi.org/10.1785/0220190386
U.S. Geological Survey. (n.d.). Aftershock forecast overview.
https://earthquake.usgs.gov/data/oaf/overview.php
U.S. Geological Survey. (n.d.). Aftershock forecast scientific background.
https://earthquake.usgs.gov/data/oaf/background.php
U.S. Geological Survey. (n.d.). Earthquake Hazards Program glossary.
https://www.usgs.gov/glossary/earthquake-hazards-program
U.S. Geological Survey. (n.d.). Foreshocks, aftershocks—What’s the difference?
https://www.usgs.gov/faqs/foreshocks-aftershocks-whats-difference
U.S. Geological Survey. (n.d.). The science of earthquakes.
https://www.usgs.gov/programs/earthquake-hazards/science-earthquakes
56

U.S. Geological Survey. (2019). Latest Earthquakes Map and List [Real-time data product].
https://www.usgs.gov/data/latest-earthquakes-map-and-list
van der Elst, N. J., Hardebeck, J. L., Michael, A. J., McBride, S. K., & Vanacore, E. (2022).
Prospective and retrospective evaluation of the U.S. Geological Survey public aftershock
forecast for the 2019–2021 Southwest Puerto Rico earthquake and aftershocks.
Seismological Research Letters, 93(2A), 620–640. https://doi.org/10.1785/0220210222
Wan, C., & Heron, P. J. (2026). Identifying main shock–aftershock sequences on the Longmen
Shan Fault: Comparison between two cluster analysis techniques. Geophysical Journal
International, 245(2). https://doi.org/10.1093/gji/ggag081
Yang, B. M., Mittal, H., & Wu, Y.-M. (2023). P-Alert earthquake early warning system: Case
study of the 2022 Chishang earthquake at Taitung, Taiwan. Terrestrial, Atmospheric and
Oceanic Sciences, 34, Article 26. https://doi.org/10.1007/s44195-023-00057-z
Yu, X., Wang, M., Ning, C., & Ji, K. (2025). Predicting largest expected aftershock ground
motions using automated machine learning (AutoML)-based scheme. Scientific Reports,
15(1), Article 942. https://doi.org/10.1038/s41598-024-84668-7
Zaliapin, I., & Ben-Zion, Y. (2013). Earthquake clusters in southern California, I: Identification
and stability. Journal of Geophysical Research: Solid Earth, 118(6), 2847–2864.
https://doi.org/10.1002/jgrb.50179
Zhang, C., Wen, W., Zhai, C., Zhang, G., Dai, N., & Zhou, B. (2025). Rapid seismic response
prediction of city-scale RC frames under mainshock–aftershock sequences using deep
57

learning and easily obtainable building information. Structures, 82, Article 110777.
https://doi.org/10.1016/j.istruc.2025.110777
Zhao, H., Chen, W., Zhang, C., & Kang, D. (2023). Rapid estimation of seismic intensities by
analyzing early aftershock sequences using the robust locally weighted regression
program (LOWESS). Natural Hazards and Earth System Sciences, 23(9), 3031–3050.
https://doi.org/10.5194/nhess-23-3031-2023
Zhao, S., Wang, H., Xue, Y., Wang, Y., Li, S., Liu, J., & Pan, G. (2021). What are more
important for aftershock spatial distribution prediction, features, or models? A case study
in China. Journal of Seismology, 26(1), 181–196.
https://doi.org/10.1007/s10950-021-10044-x
58

APPENDICES
59

ACCOUNTING DOCUMENTS
60

61

62

Appendix A: Request Letter for Earthquake Catalog
63

64

Appendix B: Request Letter for Bogo, Cebu
65

Appendix C: Activity Flow Diagram
66

Appendix D: Context Flow Diagram
67

Appendix E: Use Case Diagram
68

Appendix F: Entity Relationship Diagram
69

Appendix G: Deployment Diagram
70

Appendix H: Landing Page
71

Appendix I: Event Lists
72

Appendix J: About Page
73