# CMDB — Project: Relaunch failing Azure Fabric Pipeline Agent

> **Last Updated:** 2026-09-09  
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

### Data Flow Diagram
[External Tourism APIs]

[Seeketing IoT Beacons]   }---> (Scrapy / NiFi) ---> [Raw Lakehouse (Delta Files)]
[Local CSV/Excel Files]  /                                    |
(dbt Transformations)
v
[PowerBI Reports] <--- (DAX Queries) <--- [Gold Layer / Star Schema DB]

---

## 3. Stack Details & Configuration

### Extractor Engine (`/extractors`)
* **Framework:** Scrapy (Web scrapers) + Custom Python Async Workers.
* **Output Destination:** Azure Blob Storage (`abfss://raw-data@sitaccount.dfs.core.windows.net/`)

### Transformation Engine (`/dbt_project`)
* **Tool:** `dbt` running against Azure Fabric Synapse Data Warehouse / Lakehouse.
* **Model Layers:**
  * `stg_`: Staging models (raw schema cleanup).
  * `int_`: Intermediate transformation & join logic.
  * `fct_` / `dim_`: Fact and Dimension tables for star schema analytical reporting.

### Statistical & Impact Models (`/analytics_models`)
* **R Environment:** `renv` managed.
* **Key Packages:** `tidyverse`, `sf` (Geospatial analysis), `fixest` (Econometric modeling).
* **Models Implemented:** Regional Keynesian Multiplier assessment & Input-Output Matrix calculations.

---

## 4. Environment File Mapping & Config Keys

* **Main Config:** `config/settings.yaml`
* **Secrets Template:** `.env.example`
* **dbt Profiles:** `~/.dbt/profiles.yml` (Configured for Azure Service Principal Auth)

---

## 5. Critical Operating Constraints for AI Agents

1. **R Code Rules:** When editing R scripts in `/analytics_models`, ensure dependencies are tracked using `renv::snapshot()`. Do not install global R libraries.
2. **dbt Conventions:** All newly created models in `models/` **must** have corresponding schema descriptions and test definitions in `schema.yml`.
3. **DAX Measures:** Do not write calculated columns in Po