# Question categories

Each case has one primary category and optional secondary categories/tags. Primary labels describe the dominant analyst-facing condition; they are not difficulty ratings or outcome labels. Precise questions can still challenge a wrong premise or missing inputs. Source-only injection and contradictory headings are secondary labels on direct requests.

`classifications.jsonl` joins the frozen dataset by `case_id`; it does not change prompts, partitions, source allowlists, responses or gold labels. `taxonomy.json` defines the accepted IDs. `secondary_categories` may contain either a category ID or a secondary-tag ID.

| Category | Primary count | Definition |
| --- | ---: | --- |
| `direct` | 7 | A precise request without a dominant misleading premise, scope switch, terminology error, missing-input condition or numeric boundary. A source-only attack or defect remains a secondary label. |
| `vague` | 0 | The analyst request lacks essential scope, dates or intended outcome and requires clarification. |
| `wrong_terminology` | 2 | The analyst draft confuses named metrics, measurement periods, units or legally distinct statuses. |
| `edge_case` | 2 | The request tests equality, strict activation boundaries, precision or another explicitly limiting condition. |
| `unrelated` | 0 | The request is outside evidence search, document processing and credit analysis. |
| `misleading_premise` | 11 | The analyst presents an incorrect draft or asks for a favorable unsupported shortcut that the agent must challenge. |
| `instruction_injection` | 0 | Competing instructions attempt to replace the authorized task. For source-only payloads this is secondary to the direct analyst request. |
| `scope_confusion` | 1 | The analyst requests or permits substitution of another issuer, borrower or reporting period. |
| `missing_or_conflicting_information` | 4 | The requested conclusion depends on absent, malformed or materially conflicting source inputs. |
| `document_ambiguity` | 0 | The source itself contains contradictory wording or headings; this does not mean the analyst question is vague. |

Coverage gaps: **vague = 0; unrelated = 0**. The current 27 questions do not establish clarification behavior for underspecified requests or handling of unrelated requests. No question was relabeled to manufacture that coverage.

Instruction injection occurs in two declared source fixtures, not in the analyst wording. A category label does not prove the model encountered the payload; exposure is measured separately. Document ambiguity is secondary in 2 cases. Source acquisition/runtime gaps remain separate from question categories.

Business Agent and Gap Finder reviewed the classification approach. Additional categories can be added in a future dataset version; the running dataset remains frozen.
