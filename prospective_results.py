"""Read-only Streamlit view of GitHub Actions prospective grading reports."""
from pathlib import Path
import json
import pandas as pd
import streamlit as st

REPORTS = Path(__file__).resolve().parent / 'reports'


def render():
    st.divider()
    st.subheader('Prospective results · archived pregame quotes')
    st.caption('Reads reports committed by GitHub Actions. No odds API requests. '
               'These are hypothetical $1 settlements across recorded quotes, not a verified bet journal.')
    summary_file = REPORTS / 'summary.json'
    quotes_file = REPORTS / 'graded_quotes.csv'
    if not summary_file.exists() or not quotes_file.exists():
        st.info('No grading reports found yet. Run the Grade CFB snapshots workflow and wait for its report commit.')
        return
    try:
        summary = json.loads(summary_file.read_text(encoding='utf-8'))
        quotes = pd.read_csv(quotes_file)
    except (ValueError, OSError, pd.errors.ParserError) as exc:
        st.error(f'Unable to read grading reports: {exc}')
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Graded games', int(summary.get('graded_games', 0)))
    c2.metric('Graded quotes', int(summary.get('graded_quotes', 0)))
    c3.metric('Wins / losses / pushes', f"{summary.get('wins', 0)} / {summary.get('losses', 0)} / {summary.get('pushes', 0)}")
    c4.metric('Unique latest quotes awaiting final result or matching', int(summary.get('ungraded_not_final_or_ambiguous', 0)))
    missing = int(summary.get('missing_prediction_or_price', 0))
    st.caption(f"Snapshot rows processed: {int(summary.get('input_rows', 0)):,}. "
               f"Rows lacking a prediction or price: {missing:,} (includes older snapshots). "
               'Awaiting-results counts may also include ambiguous game matches.')
    if quotes.empty:
        st.info('No settled, eligible quotes yet. This section will populate when final scores are available and grading reruns.')
        return
    required = {'game_id', 'sportsbook_key', 'selection', 'spread', 'american_odds',
                'captured_at_utc', 'selection_result', 'one_unit_profit'}
    absent = required - set(quotes.columns)
    if absent:
        st.error('Graded report is missing columns: ' + ', '.join(sorted(absent)))
        return
    quotes['one_unit_profit'] = pd.to_numeric(quotes['one_unit_profit'], errors='coerce')
    quotes = quotes.dropna(subset=['one_unit_profit']).copy()
    if quotes.empty:
        st.info('No valid settled quote profits in the report.')
        return
    st.warning('Multiple books, selections and capture times for one game are correlated. '
               'All-quote returns below do not represent independent bets or a validated strategy.')
    c1, c2, c3 = st.columns(3)
    c1.metric('Hypothetical $1 per quote net', f"${quotes['one_unit_profit'].sum():,.2f}")
    c2.metric('Hypothetical all-quote ROI', f"{quotes['one_unit_profit'].mean():.1%}")
    c3.metric('Distinct games with settled quotes', quotes['game_id'].nunique())
    by_book = (quotes.groupby('sportsbook_key', dropna=False)
               .agg(quotes=('selection_result', 'size'),
                    wins=('selection_result', lambda x: int((x == 'win').sum())),
                    losses=('selection_result', lambda x: int((x == 'loss').sum())),
                    pushes=('selection_result', lambda x: int((x == 'push').sum())),
                    net_per_unit=('one_unit_profit', 'sum'),
                    hypothetical_roi=('one_unit_profit', 'mean'))
               .reset_index().sort_values('sportsbook_key'))
    st.markdown('**Results by sportsbook (descriptive, not ranked)**')
    st.dataframe(by_book, hide_index=True, use_container_width=True)
    st.markdown('**All settled archived quotes**')
    st.dataframe(quotes.sort_values(['kickoff_utc', 'game_id', 'sportsbook_key']),
                 hide_index=True, use_container_width=True)
    st.download_button('Download graded quotes', quotes.to_csv(index=False),
                       file_name='graded_cfb_quotes.csv', mime='text/csv', key='download_graded_cfb')

if __name__ == '__main__':
    render()
