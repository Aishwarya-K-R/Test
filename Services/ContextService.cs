using System.Text;
using Microsoft.EntityFrameworkCore;
using Patient_Management_System.Data;

namespace Patient_Management_System.Services
{
    public class ContextService(AppDbContext db)
    {
        private readonly AppDbContext _db = db;

        // Get all patient IDs
        public async Task<List<int>> GetAllPatientIdsAsync()
        {
            return await _db.Patients.Select(p => p.Id).ToListAsync();
        }

        public async Task<Dictionary<int, string>> GetPatientContextDictAsync(List<int> patientIds)
        {
            var query = _db.Patients
                .Where(p => patientIds.Contains(p.Id))
                .Select(p => new
                {
                    p.Id,
                    p.Name,
                    p.DateOfBirth,
                    BillingAccountId = _db.Billings
                        .Where(b => b.PatientId == p.Id)
                        .Select(b => b.AccountId)
                        .FirstOrDefault()
                });

            var data = await query.ToListAsync();
            var dict = new Dictionary<int, string>();

            foreach (var d in data)
            {
                var age = CalculateAge(d.DateOfBirth);
                var maskedBilling = Mask(d.BillingAccountId);
                dict[d.Id] = $"Patient: {d.Name}, Age: {age}, BillingAccountId: {maskedBilling}";
            }

            return dict;
        }

        private int CalculateAge(DateOnly dob)
        {
            var today = DateTime.UtcNow.Date;
            var age = today.Year - dob.Year;
            if (dob > DateOnly.FromDateTime(today).AddYears(-age)) age--;
            return age;
        }

        private string Mask(string? value)
        {
            if (string.IsNullOrEmpty(value)) return "N/A";
            return new string('*', value.Length - 4) + value[^4..];
        }
    }
}