// src/components/HistoricalBanner.tsx
export function HistoricalBanner() {
    return (
        <div style={{
            backgroundColor: '#fff3cd',
            border: '1px solid #ffeaa7',
            borderRadius: '4px',
            padding: '8px 12px',
            marginBottom: '16px',
            fontSize: '14px',
            color: '#856404'
        }}>
            📋 Viewing a past step — submitting will branch the thread here
        </div>
    );
}