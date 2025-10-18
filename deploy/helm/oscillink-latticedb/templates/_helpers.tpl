{{- define "oscillink-latticedb.name" -}}
{{- .Chart.Name -}}
{{- end -}}

{{- define "oscillink-latticedb.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "oscillink-latticedb.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
