# SEIS Model Feature Engineering Improvement Report
Comparing backup version `v2_pre_improvement` against active/updated models.

> [!NOTE]
> Lower is better for **Brier**, **ECE**, **RMSE**, and **MAE**.
> Higher is better for **ROC-AUC**, **AP**, and **R²**.
> Deltas are formatted as **<span style='color:green'>green</span>** for improvement and **<span style='color:red'>red</span>** for regression.

## Ensemble Model (SEIS) Comparison
### Year: 2025
#### Classification Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| aftershock_24h | Brier | 0.0395 | 0.0393 | <span style='color:green'>-0.0002</span> |
|  | ECE | 0.0080 | 0.0084 | <span style='color:red'>+0.0004</span> |
|  | ROC-AUC | 0.9841 | 0.9842 | <span style='color:green'>+0.0000</span> |
|  | AP | 0.9777 | 0.9778 | <span style='color:green'>+0.0001</span> |
| aftershock_within_10km_24h | Brier | 0.0464 | 0.0460 | <span style='color:green'>-0.0005</span> |
|  | ECE | 0.0074 | 0.0086 | <span style='color:red'>+0.0012</span> |
|  | ROC-AUC | 0.9782 | 0.9783 | <span style='color:green'>+0.0001</span> |
|  | AP | 0.9591 | 0.9599 | <span style='color:green'>+0.0007</span> |
| aftershock_within_25km_24h | Brier | 0.0429 | 0.0428 | <span style='color:green'>-0.0000</span> |
|  | ECE | 0.0069 | 0.0070 | <span style='color:red'>+0.0001</span> |
|  | ROC-AUC | 0.9817 | 0.9816 | <span style='color:red'>-0.0001</span> |
|  | AP | 0.9716 | 0.9716 | <span style='color:green'>+0.0000</span> |
| aftershock_within_50km_24h | Brier | 0.0406 | 0.0403 | <span style='color:green'>-0.0003</span> |
|  | ECE | 0.0071 | 0.0066 | <span style='color:green'>-0.0005</span> |
|  | ROC-AUC | 0.9832 | 0.9832 | <span style='color:green'>+0.0000</span> |
|  | AP | 0.9754 | 0.9755 | <span style='color:green'>+0.0001</span> |
| aftershock_beyond_50km_24h | Brier | 0.0066 | 0.0069 | <span style='color:red'>+0.0003</span> |
|  | ECE | 0.0012 | 0.0029 | <span style='color:red'>+0.0017</span> |
|  | ROC-AUC | 0.9770 | 0.9749 | <span style='color:red'>-0.0021</span> |
|  | AP | 0.4967 | 0.4961 | <span style='color:red'>-0.0006</span> |

#### Regression Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| max_aftershock_mag_24h | RMSE | 0.6205 | 0.6192 | <span style='color:green'>-0.0013</span> |
|  | MAE | 0.4692 | 0.4722 | <span style='color:red'>+0.0030</span> |
|  | R² | 0.7053 | 0.7065 | <span style='color:green'>+0.0012</span> |
| nearest_aftershock_distance_km_24h | RMSE | 33.0102 | 32.8456 | <span style='color:green'>-0.1646</span> |
|  | MAE | 6.0407 | 6.0513 | <span style='color:red'>+0.0106</span> |
|  | R² | 0.4488 | 0.4543 | <span style='color:green'>+0.0055</span> |
| median_aftershock_distance_km_24h | RMSE | 41.0637 | 40.7584 | <span style='color:green'>-0.3053</span> |
|  | MAE | 13.2056 | 13.1598 | <span style='color:green'>-0.0458</span> |
|  | R² | 0.5658 | 0.5722 | <span style='color:green'>+0.0064</span> |
| p90_aftershock_distance_km_24h | RMSE | 61.2814 | 61.4777 | <span style='color:red'>+0.1963</span> |
|  | MAE | 27.1524 | 26.9684 | <span style='color:green'>-0.1840</span> |
|  | R² | 0.4779 | 0.4746 | <span style='color:red'>-0.0034</span> |

## Individual Family Model Comparisons
### Family: CATBOOST
#### CATBOOST Classification Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| aftershock_24h | Brier | 0.0395 | 0.0437 | <span style='color:red'>+0.0042</span> |
|  | ECE | 0.0080 | 0.0157 | <span style='color:red'>+0.0076</span> |
|  | ROC-AUC | 0.9841 | 0.9818 | <span style='color:red'>-0.0024</span> |
|  | AP | 0.9777 | 0.9700 | <span style='color:red'>-0.0077</span> |
| aftershock_within_10km_24h | Brier | 0.0464 | 0.0486 | <span style='color:red'>+0.0022</span> |
|  | ECE | 0.0074 | 0.0113 | <span style='color:red'>+0.0040</span> |
|  | ROC-AUC | 0.9782 | 0.9758 | <span style='color:red'>-0.0024</span> |
|  | AP | 0.9591 | 0.9476 | <span style='color:red'>-0.0115</span> |
| aftershock_within_25km_24h | Brier | 0.0429 | 0.0461 | <span style='color:red'>+0.0032</span> |
|  | ECE | 0.0069 | 0.0137 | <span style='color:red'>+0.0069</span> |
|  | ROC-AUC | 0.9817 | 0.9793 | <span style='color:red'>-0.0023</span> |
|  | AP | 0.9716 | 0.9628 | <span style='color:red'>-0.0088</span> |
| aftershock_within_50km_24h | Brier | 0.0406 | 0.0445 | <span style='color:red'>+0.0039</span> |
|  | ECE | 0.0071 | 0.0149 | <span style='color:red'>+0.0078</span> |
|  | ROC-AUC | 0.9832 | 0.9808 | <span style='color:red'>-0.0024</span> |
|  | AP | 0.9754 | 0.9673 | <span style='color:red'>-0.0082</span> |
| aftershock_beyond_50km_24h | Brier | 0.0066 | 0.0062 | <span style='color:green'>-0.0004</span> |
|  | ECE | 0.0012 | 0.0011 | <span style='color:green'>-0.0002</span> |
|  | ROC-AUC | 0.9770 | 0.9771 | <span style='color:green'>+0.0001</span> |
|  | AP | 0.4967 | 0.5214 | <span style='color:green'>+0.0247</span> |

#### CATBOOST Regression Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| max_aftershock_mag_24h | RMSE | 0.6205 | 0.6329 | <span style='color:red'>+0.0124</span> |
|  | MAE | 0.4692 | 0.4913 | <span style='color:red'>+0.0222</span> |
|  | R² | 0.7053 | 0.6876 | <span style='color:red'>-0.0177</span> |
| nearest_aftershock_distance_km_24h | RMSE | 33.8682 | 34.7739 | <span style='color:red'>+0.9057</span> |
|  | MAE | 6.1503 | 6.4147 | <span style='color:red'>+0.2644</span> |
|  | R² | 0.4198 | 0.4039 | <span style='color:red'>-0.0159</span> |
| median_aftershock_distance_km_24h | RMSE | 42.1227 | 42.4992 | <span style='color:red'>+0.3765</span> |
|  | MAE | 12.8079 | 12.2303 | <span style='color:green'>-0.5777</span> |
|  | R² | 0.5431 | 0.5148 | <span style='color:red'>-0.0283</span> |
| p90_aftershock_distance_km_24h | RMSE | 63.2500 | 60.8312 | <span style='color:green'>-2.4188</span> |
|  | MAE | 27.8020 | 24.7721 | <span style='color:green'>-3.0299</span> |
|  | R² | 0.4438 | 0.4658 | <span style='color:green'>+0.0220</span> |

### Family: LIGHTGBM
#### LIGHTGBM Classification Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| aftershock_24h | Brier | 0.0392 | 0.0409 | <span style='color:red'>+0.0017</span> |
|  | ECE | 0.0078 | 0.0083 | <span style='color:red'>+0.0005</span> |
|  | ROC-AUC | 0.9841 | 0.9828 | <span style='color:red'>-0.0014</span> |
|  | AP | 0.9779 | 0.9732 | <span style='color:red'>-0.0047</span> |
| aftershock_within_10km_24h | Brier | 0.0458 | 0.0458 | <span style='color:green'>-0.0000</span> |
|  | ECE | 0.0072 | 0.0079 | <span style='color:red'>+0.0007</span> |
|  | ROC-AUC | 0.9783 | 0.9770 | <span style='color:red'>-0.0012</span> |
|  | AP | 0.9600 | 0.9532 | <span style='color:red'>-0.0068</span> |
| aftershock_within_25km_24h | Brier | 0.0427 | 0.0435 | <span style='color:red'>+0.0008</span> |
|  | ECE | 0.0058 | 0.0073 | <span style='color:red'>+0.0015</span> |
|  | ROC-AUC | 0.9815 | 0.9803 | <span style='color:red'>-0.0013</span> |
|  | AP | 0.9717 | 0.9664 | <span style='color:red'>-0.0053</span> |
| aftershock_within_50km_24h | Brier | 0.0402 | 0.0417 | <span style='color:red'>+0.0015</span> |
|  | ECE | 0.0057 | 0.0066 | <span style='color:red'>+0.0009</span> |
|  | ROC-AUC | 0.9831 | 0.9818 | <span style='color:red'>-0.0014</span> |
|  | AP | 0.9756 | 0.9706 | <span style='color:red'>-0.0050</span> |
| aftershock_beyond_50km_24h | Brier | 0.0068 | 0.0063 | <span style='color:green'>-0.0004</span> |
|  | ECE | 0.0031 | 0.0024 | <span style='color:green'>-0.0007</span> |
|  | ROC-AUC | 0.9761 | 0.9767 | <span style='color:green'>+0.0006</span> |
|  | AP | 0.4917 | 0.5177 | <span style='color:green'>+0.0260</span> |

#### LIGHTGBM Regression Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| max_aftershock_mag_24h | RMSE | 0.6483 | 0.6934 | <span style='color:red'>+0.0451</span> |
|  | MAE | 0.4997 | 0.5397 | <span style='color:red'>+0.0401</span> |
|  | R² | 0.6783 | 0.6250 | <span style='color:red'>-0.0532</span> |
| nearest_aftershock_distance_km_24h | RMSE | 33.0102 | 33.6119 | <span style='color:red'>+0.6017</span> |
|  | MAE | 6.0407 | 6.3170 | <span style='color:red'>+0.2763</span> |
|  | R² | 0.4488 | 0.4431 | <span style='color:red'>-0.0057</span> |
| median_aftershock_distance_km_24h | RMSE | 41.2173 | 40.3206 | <span style='color:green'>-0.8967</span> |
|  | MAE | 13.3863 | 12.6038 | <span style='color:green'>-0.7825</span> |
|  | R² | 0.5625 | 0.5633 | <span style='color:green'>+0.0007</span> |
| p90_aftershock_distance_km_24h | RMSE | 61.2814 | 59.3932 | <span style='color:green'>-1.8882</span> |
|  | MAE | 27.1524 | 24.4950 | <span style='color:green'>-2.6575</span> |
|  | R² | 0.4779 | 0.4907 | <span style='color:green'>+0.0128</span> |

### Family: RANDOM-FOREST
#### RANDOM-FOREST Classification Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| aftershock_24h | Brier | 0.0431 | 0.0445 | <span style='color:red'>+0.0013</span> |
|  | ECE | 0.0272 | 0.0266 | <span style='color:green'>-0.0006</span> |
|  | ROC-AUC | 0.9800 | 0.9794 | <span style='color:red'>-0.0007</span> |
|  | AP | 0.9737 | 0.9692 | <span style='color:red'>-0.0045</span> |
| aftershock_within_10km_24h | Brier | 0.0528 | 0.0547 | <span style='color:red'>+0.0019</span> |
|  | ECE | 0.0382 | 0.0419 | <span style='color:red'>+0.0037</span> |
|  | ROC-AUC | 0.9740 | 0.9729 | <span style='color:red'>-0.0011</span> |
|  | AP | 0.9539 | 0.9449 | <span style='color:red'>-0.0090</span> |
| aftershock_within_25km_24h | Brier | 0.0463 | 0.0469 | <span style='color:red'>+0.0006</span> |
|  | ECE | 0.0264 | 0.0271 | <span style='color:red'>+0.0007</span> |
|  | ROC-AUC | 0.9775 | 0.9770 | <span style='color:red'>-0.0005</span> |
|  | AP | 0.9674 | 0.9625 | <span style='color:red'>-0.0049</span> |
| aftershock_within_50km_24h | Brier | 0.0443 | 0.0453 | <span style='color:red'>+0.0011</span> |
|  | ECE | 0.0265 | 0.0265 | <span style='color:green'>-0.0000</span> |
|  | ROC-AUC | 0.9790 | 0.9783 | <span style='color:red'>-0.0007</span> |
|  | AP | 0.9713 | 0.9666 | <span style='color:red'>-0.0047</span> |
| aftershock_beyond_50km_24h | Brier | 0.0068 | 0.0065 | <span style='color:green'>-0.0004</span> |
|  | ECE | 0.0026 | 0.0021 | <span style='color:green'>-0.0005</span> |
|  | ROC-AUC | 0.9729 | 0.9718 | <span style='color:red'>-0.0011</span> |
|  | AP | 0.4949 | 0.5087 | <span style='color:green'>+0.0139</span> |

#### RANDOM-FOREST Regression Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| max_aftershock_mag_24h | RMSE | 0.6564 | 0.6740 | <span style='color:red'>+0.0176</span> |
|  | MAE | 0.5135 | 0.5342 | <span style='color:red'>+0.0207</span> |
|  | R² | 0.6702 | 0.6457 | <span style='color:red'>-0.0245</span> |
| nearest_aftershock_distance_km_24h | RMSE | 37.9486 | 38.3173 | <span style='color:red'>+0.3687</span> |
|  | MAE | 6.6029 | 6.8384 | <span style='color:red'>+0.2355</span> |
|  | R² | 0.2715 | 0.2762 | <span style='color:green'>+0.0047</span> |
| median_aftershock_distance_km_24h | RMSE | 50.8492 | 49.1492 | <span style='color:green'>-1.7000</span> |
|  | MAE | 15.2947 | 14.3019 | <span style='color:green'>-0.9928</span> |
|  | R² | 0.3342 | 0.3511 | <span style='color:green'>+0.0169</span> |
| p90_aftershock_distance_km_24h | RMSE | 69.2670 | 66.9871 | <span style='color:green'>-2.2799</span> |
|  | MAE | 32.5858 | 28.0729 | <span style='color:green'>-4.5128</span> |
|  | R² | 0.3330 | 0.3522 | <span style='color:green'>+0.0192</span> |

### Family: XGBOOST
#### XGBOOST Classification Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| aftershock_24h | Brier | 0.0395 | 0.0418 | <span style='color:red'>+0.0023</span> |
|  | ECE | 0.0078 | 0.0108 | <span style='color:red'>+0.0029</span> |
|  | ROC-AUC | 0.9840 | 0.9822 | <span style='color:red'>-0.0018</span> |
|  | AP | 0.9776 | 0.9719 | <span style='color:red'>-0.0057</span> |
| aftershock_within_10km_24h | Brier | 0.0460 | 0.0469 | <span style='color:red'>+0.0010</span> |
|  | ECE | 0.0079 | 0.0096 | <span style='color:red'>+0.0016</span> |
|  | ROC-AUC | 0.9783 | 0.9765 | <span style='color:red'>-0.0018</span> |
|  | AP | 0.9599 | 0.9514 | <span style='color:red'>-0.0085</span> |
| aftershock_within_25km_24h | Brier | 0.0429 | 0.0442 | <span style='color:red'>+0.0013</span> |
|  | ECE | 0.0064 | 0.0086 | <span style='color:red'>+0.0021</span> |
|  | ROC-AUC | 0.9815 | 0.9798 | <span style='color:red'>-0.0017</span> |
|  | AP | 0.9715 | 0.9651 | <span style='color:red'>-0.0064</span> |
| aftershock_within_50km_24h | Brier | 0.0405 | 0.0425 | <span style='color:red'>+0.0019</span> |
|  | ECE | 0.0065 | 0.0102 | <span style='color:red'>+0.0037</span> |
|  | ROC-AUC | 0.9831 | 0.9813 | <span style='color:red'>-0.0018</span> |
|  | AP | 0.9753 | 0.9694 | <span style='color:red'>-0.0060</span> |
| aftershock_beyond_50km_24h | Brier | 0.0067 | 0.0062 | <span style='color:green'>-0.0005</span> |
|  | ECE | 0.0019 | 0.0011 | <span style='color:green'>-0.0008</span> |
|  | ROC-AUC | 0.9746 | 0.9760 | <span style='color:green'>+0.0014</span> |
|  | AP | 0.5017 | 0.5151 | <span style='color:green'>+0.0134</span> |

#### XGBOOST Regression Performance
| Target | Metric | Backup | Updated | Delta |
| :--- | :--- | :---: | :---: | :---: |
| max_aftershock_mag_24h | RMSE | 0.6534 | 0.6523 | <span style='color:green'>-0.0011</span> |
|  | MAE | 0.5065 | 0.5082 | <span style='color:red'>+0.0017</span> |
|  | R² | 0.6732 | 0.6681 | <span style='color:red'>-0.0051</span> |
| nearest_aftershock_distance_km_24h | RMSE | 34.4062 | 35.0964 | <span style='color:red'>+0.6902</span> |
|  | MAE | 6.1781 | 6.4339 | <span style='color:red'>+0.2558</span> |
|  | R² | 0.4012 | 0.3928 | <span style='color:red'>-0.0084</span> |
| median_aftershock_distance_km_24h | RMSE | 41.0637 | 39.9041 | <span style='color:green'>-1.1595</span> |
|  | MAE | 13.2056 | 12.3107 | <span style='color:green'>-0.8949</span> |
|  | R² | 0.5658 | 0.5723 | <span style='color:green'>+0.0065</span> |
| p90_aftershock_distance_km_24h | RMSE | 61.6407 | 60.9720 | <span style='color:green'>-0.6686</span> |
|  | MAE | 26.9790 | 24.8002 | <span style='color:green'>-2.1789</span> |
|  | R² | 0.4718 | 0.4633 | <span style='color:red'>-0.0085</span> |
