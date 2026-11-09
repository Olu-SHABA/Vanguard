# John Doe

Stirling, UK | john.doe@vanguardops.co.uk | +44 0000 000000

**Code, commit history and documentation for every project below: https://github.com/Olu-SHABA**

---

## PROFESSIONAL SUMMARY

Versatile and results-driven Data Scientist and Network Operations Professional with extensive experience in machine learning, data analytics, network management, and IT infrastructure. Skilled in Python, SQL, PostgreSQL, Tableau, and cloud-based analytics platforms to develop predictive models, automate ETL workflows, and design real-time KPI dashboards that drive operational efficiency and informed decision-making. Proven track record in managing complex multi-vendor network environments, optimizing performance, and ensuring high service uptime. Combines analytical rigor with hands-on technical expertise, delivering scalable solutions, reducing operational costs, and enhancing service reliability across telecommunications and enterprise data domains.

---

## TECHNICAL SKILLS

- **Programming Languages:** Python, JavaScript, CSS3, XML
- **Databases:** Microsoft SQL, MySQL, PostgreSQL
- **Operating Systems:** Microsoft Windows Server
- **Machine Learning:** Scikit-learn, TensorFlow, PyTorch
- **Other Software:** MATLAB, Maple, Tableau, Microsoft Power BI, DAX, cloud computing, Seaborn, Matplotlib, NumPy, Pandas
- **Collaborative Tools:** Slack, TeamViewer, Zoom, Microsoft Office (Word, Excel, PowerPoint), Google Workspace (Docs, Sheets, Slides)

---

## CORE COMPETENCIES

| | | |
|---|---|---|
| Statistical Modeling | Exploratory Data Analysis (EDA) | Reporting & Dashboards |
| Machine Learning | Feature Engineering | Quality Assurance Testing |
| Data Mining | Data Visualization | Data Storytelling |
| Predictive Analytics | Model Deployment | Cross-Functional Teams |
| Data Wrangling | A/B Testing | Problem-Solving |

---

## PROFESSIONAL EXPERIENCE

### Consultant (Data Scientist)
**Amdari Inc. — UK** | October 2025 – Present

- Developed and deployed machine learning models using Python and Scikit-Learn, increasing demand forecasting accuracy by 20%, optimizing inventory and resource allocation.
- Automated data pipelines and ETL workflows in Python, reducing data processing time by 50% and enabling near real-time analytics.
- Designed, optimized, and maintained PostgreSQL databases, improving query performance and reducing data retrieval times by 35% while maintaining high data integrity.
- Built interactive dashboards in Tableau to visualize KPIs and operational trends, helping stakeholders make data-driven decisions, increasing operational efficiency by 30%.
- Performed statistical analysis and predictive modeling in Python and Excel, identifying key trends that drove a 15% increase in client retention through targeted strategies.
- Implemented scalable workflows in Jupyter and Google Colab, streamlining model development and deployment while reducing manual effort by 40%.
- Integrated SQL, Python, and cloud platforms to manage large datasets (>300k records), improving accessibility and enabling advanced analytics.
- Conducted A/B testing and cohort analysis in Python, supporting marketing and product strategies that increased engagement and revenue by 10–15%.
- Developed real-time KPI monitoring dashboards using Tableau and Power BI, tracking metrics such as revenue, churn, and operational efficiency, improving executive visibility.

### NOC Engineer
**Avanti Communications — New Quay, UK** | October 2024 – July 2025

- Monitored and maintained Cisco, Juniper, and satellite hub networks, achieving 99.99% network uptime and ensuring seamless connectivity for clients.
- Managed network and hub-related incidents, acting as Incident Manager for P1/P2 cases, coordinating resolution and minimizing service disruptions.
- Escalated complex issues to specialist teams and vendors, facilitating effective NOC-to-NOC interactions and ensuring timely problem resolution.
- Coordinated with vendors and cross-functional NOC teams to enforce change management compliance, maintaining operational standards and service reliability.
- Updated and optimized operational procedures and knowledge base documentation, reducing Mean Time to Resolution (MTTR) and enhancing team efficiency.
- Conducted proactive maintenance and continuous monitoring of network and hub infrastructure, including Gateway Operations and GES antennas, ensuring full service availability and resilience.

### Network Service Management Specialist
**MTN Communications PLC — Nigeria** | September 2018 – September 2024

- Designed and implemented multi-vendor network solutions integrating Cisco, Comtech, and Viasat satellite technologies, enhancing cross-platform interoperability and service reliability.
- Designed and deployed a vectorized network reporting engine in Python, automating a manual extract-clean-transform-load cycle that previously consumed 60–90 minutes of analyst time per run; reduced execution to under 2 seconds on annual datasets exceeding 800,000 rows, across daily, weekly and annual reporting cadences. Implemented input validation and null-handling logic — missing values imputed with time-based defaults rather than dropped, preserving record completeness — and scheduled the daily cycle for unattended 06:00 execution.
- Trained peer and junior engineers on the reporting engine and associated operational procedures, producing handover documentation and supporting adoption across daily, weekly and annual reporting cycles.
- Applied traffic engineering strategies to optimize network performance, reducing congestion incidents by 20% and improving end-user experience.
- Enhanced network visibility and control, achieving 18% better capacity utilization and 12% lower latency, supporting more efficient data transmission and service delivery.
- Conducted fault diagnosis and proactive service improvement analyses in alignment with ITIL frameworks, identifying risks and implementing preventive measures.

### Network Services Management Engineer
**MTN Communications — Nigeria** | April 2012 – August 2018

- Developed and implemented process improvements that reduced incident response time by 40%, enhancing network reliability and operational efficiency.
- Coordinated end-to-end resolution of major network incidents, performing Root Cause Analysis (RCA) on every incident to prevent recurrence and improve system resilience.
- Managed incident ownership with potential or actual business impact, ensuring timely communication with affected stakeholders and maintaining high service continuity.

### Satellite Network Operations Center (NOC) Engineer
**MTN Communications — Nigeria** | June 2007 – April 2012

- Managed satellite network operations to ensure optimal performance, reliability, and uptime, supporting mission-critical communication services.
- Performed troubleshooting and resolution of network issues, reducing downtime and maintaining high service continuity across VSAT and satellite networks.

### Network Operations Center (NOC) Engineer
**VGC Communications — Nigeria** | July 2005 – January 2007

- Delivered service assurance and support for customers, maintaining continuous service operation in alignment with established quality levels and SLA commitments.
- Monitored Value-Added Networks (TDMA and SCPC Satellite Networks), performing first- and second-level attention, diagnosis, and resolution of network incidents to ensure high service reliability.

### Cisco Instructor / Network Administrator
**Training Height — Nigeria** | January 2002 – June 2005

- Developed and delivered Cisco CCNA and CCNP training programs to IT professionals, enhancing technical competencies and certification success rates.

---

## PROJECTS

Seven published repositories at **https://github.com/Olu-SHABA** — source, commit history and documentation open to inspection.

### Network Operations Report Engine
**Python · Pandas · NumPy · regex · concurrent I/O** | 2024 – 2026

- Built a Python ETL engine automating NOC reporting, replacing procedural loops with vectorised Pandas and NumPy operations performed in memory.
- Implemented parallel drive scanning and regex-based vendor routing to consolidate reports across a multi-vendor estate.
- Added file-lock handling so a report held open by a user cannot halt the pipeline.
- Originally built for network operations reporting at MTN Communications; being extended into a domain-agnostic reporting tool.

### Customer Lifetime Value and Churn Analytics
**Python · Pandas · Scikit-learn · K-Means · RFM** | 2026

- Built an e-commerce analytics pipeline applying customer cohort sequencing and RFM feature engineering to transaction data.
- Segmented customers using K-Means clustering with hyperparameter tuning, isolating behavioural profiles for targeted marketing.
- Produced diagnostic outputs mapping each segment to a marketing action.

### Vanguard — semi-autonomous application pipeline
**Python · sentence-transformers · SQLite · pytest · IMAP** | 2026

- Built a Python pipeline that ingests job adverts from board APIs, scores them against a canonical CV using sentence-transformer embeddings, and classifies every unmet requirement.
- Designed the scoring to gate on requirement coverage rather than document similarity, so every score can name which requirement failed.
- Implemented IMAP and Gmail polling with four-stage message correlation to track applications through to outcome.

### Further repositories

- **Hotel Revenue Optimisation Engine** *(Python, Scikit-learn, ensemble methods)* — models predicting booking cancellations, supporting inventory allocation decisions.
- **Kinetix** *(Python, REST, JSON Schema)* — configuration-driven harvesting engine with token pagination, schema validation and atomic file writes.
- **Trager Data Service** *(Python, FastAPI, async, Pandas)* — asynchronous endpoints offloading blocking Pandas operations via `run_in_threadpool`, with NaN-to-None serialisation handling.
- **Trager Chat Service** *(Python, FastAPI, Pydantic, LLM APIs)* — service wrapping LLM inference, with global exception middleware and validated request handling.

---

## EDUCATION

**B.Sc. Civil Engineering** — Obafemi Awolowo University, Ile-Ife, Nigeria | 2002

---

## CERTIFICATIONS

**Full Stack Data Science** — 10Alytics, 2025
