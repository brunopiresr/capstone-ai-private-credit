# Data sources

| Source | Use |
| --- | --- |
| [Synthetic financials and terms](../../data/app/synthetic/) | Fictional borrower assessments and demonstrations |
| [SEC catalog](../../data/app/sec/public_sec_documents.csv) | Public filing URLs, identity, and dates for HTML extraction and search |
| Local HTML, Markdown, and SQLite extractions | Cached source text, quotations, and provenance |
| [Evaluation data](../../data/evaluation/) | Expected answers and historical observations; excluded from runtime evidence |

Public issuers and synthetic borrowers are separate. Link sources explicitly; names
and tickers do not establish a relationship. Financial notes that reveal outcomes are
excluded from agent inputs. Reporting dates do not establish publication availability.

See [data layout and downloads](../../data/README.md). SEC company-facts feeds,
investor-relations collection, and live public news are not implemented.
