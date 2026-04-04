using Patient_Management_System.Models;

namespace Patient_Management_System.Services
{
    public interface IPatientService
    {
        Task<IEnumerable<Patient>> GetPatientsAsync(string search, string sortCol, string sortDir, int pageNo, int pageSize);
        Task<Patient> GetPatientByIdAsync(int id);
        Task<Patient> CreatePatientAsync(Patient patient);
        Task<Patient> UpdatePatientAsync(int id, Patient patient);
        Task DeletePatientAsync(int id);
    }
}
