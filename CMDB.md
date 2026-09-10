# CMDB — Project: Hermes Agent relaunching failed Azure Fabric Pipeline 

> **Last Updated:** 2026-09-10 
> **Environment Context:** Developement / Azure Cloud  
> **Owner/Team:** Data Architecture & operations (`@data-platform`)  

## 1. System Metadata

| Attribute | Value | Posible values
| :--- | :--- | :--- |
| **System Name** | `Hermes AI Test` | Project-name
| **Core Languages** | Python 3.12.3 | Python 3.11, R 4.4, SQL (T-SQL / Postgres)
| **Data Platform** | Microsoft Azure Fabric (Medallion architecture) | Microsoft Azure Fabric (Lakehouse architecture)
| **Scraping Framework** | None | Scrapy 2.11 / Python `requests`
| **Transformation Layer** | None | dbt-core 1.8 (`dbt-fabric` adapter)
| **Orchestration** | Azure Fabric Pipeline | Apache NiFi / n8n / Azure Data Factory 
| **BI & Analytics** | None | PowerBI Embedded / DAX Queries 

---

## 2. Component Architecture

### Data Flow Diagra
````
[Cron with Local/Hosted Hermes AI Agent profile with skills/tools/Python Plugins] 
     |
     |<--> [Local/Cloud SLM/LLM]
     |
     |<--> Plugin fabric_pipeline_monitor.py - connecting to Azure Fabric API (with Microsoft Entra ID / OAuth2)
     |
     |<--> Skill
     |
     |<--> Tool
     

````
---
