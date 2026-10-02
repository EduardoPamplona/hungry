{{/*
Shared env block for the api Deployment and the ingest Job — both run the same
planner-api image and need the same DB / TEI / LLM wiring.
*/}}
{{- define "hungry.api.env" -}}
- name: DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ .Release.Name }}-db-app   # CNPG-generated app-user secret
      key: uri
- name: TEI_URL
  value: "http://{{ .Release.Name }}-tei:80"
- name: LLM_BACKEND
  value: {{ .Values.llmBackend | quote }}
- name: HOSTED_BASE_URL
  value: {{ .Values.hostedBaseUrl | quote }}
- name: HOSTED_MODEL
  value: {{ .Values.hostedModel | quote }}
- name: HOSTED_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.hostedSecret }}
      key: HOSTED_API_KEY
{{- end -}}
