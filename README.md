# Your Project Name

AI Credit Monitoring - Private Credit Covenant & Early-Warning Agent

## The Problem

Private-credit teams must piece together loan terms, borrower financials, and historical performance to understand whether a borrower is meeting its obligations and whether its credit risk is increasing. Manual monitoring takes time and can delay the discovery of emerging problems. AI Credit Monitoring aims to produce evidence-backed assessments and early warnings, helping analysts focus on the borrowers that need attention while allowing firms to oversee larger portfolios efficiently

## What It Does

AI Credit Monitoring brings together loan agreements, borrower financial data, and historical results to assess a borrower’s covenant compliance and identify signs of increasing credit risk. It calculates key measures, tracks changes over time, and produces an evidence-backed assessment that analysts can review, portfolio managers can use to prioritize attention, and risk teams can verify. 

### Capstone Project Scope

This project addresses on one part of the problem: monitoring a net leverage covenant and its trend


### Capstone System Interaction

## Setup

1. Install uv if you don't have it yet: https://docs.astral.sh/uv/getting-started/installation/

2. Clone this repository (or download the zip and extract it).

3. Create a `.env` file from the template and add your API key:

       cp .env.example .env

4. Install dependencies:

       uv sync

5. Start Jupyter:

       uv run jupyter notebook

## Notebooks

- `notebooks/01-setup.ipynb` - smoke test that confirms your environment works
- `notebooks/02-rag.ipynb` - a minimal RAG baseline you can adapt to your own data

## Data

Put your project data in the `data/` folder. See `notebooks/02-rag.ipynb` for how to load it.
