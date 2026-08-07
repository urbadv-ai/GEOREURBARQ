# G5-L07 IDE-Sisema

Pipeline controlado para materialização do sub-snapshot operacional das 19 camadas WFS admitidas na etapa metadata-first.

A primeira execução (`probe_l07_wfs.py`) congela DescribeFeatureType, cardinalidade por resultType=hits e uma feição-amostra. Ela não substitui a coleta integral. Seu objetivo é dimensionar a paginação e impedir truncamento silencioso antes do sub-snapshot completo.
