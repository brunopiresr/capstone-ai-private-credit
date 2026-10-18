# Data sources

Implemented inputs are the [SEC filing catalog](../data/public_sec_documents.csv), cached
HTML/Markdown, stored extractions, and controlled synthetic borrower financials/covenant
terms. The [shared download command](../data/README.md#sec-source-download) populates the
HTML cache used by services and notebooks. The catalog supplies source URLs and document
metadata; extraction and retrieval retain exact quotes and provenance.

Synthetic gold labels are acceptance expectations, not runtime evidence. Financial CSV
notes can reveal expected outcomes and are excluded from agent inputs. Reporting dates
and actual source availability are distinct; unknown availability remains unknown.

SEC company-facts feeds, issuer investor-relations collection, and a general public-news
provider are planned, not implemented. See the [current architecture and roadmap](architecture.md).
