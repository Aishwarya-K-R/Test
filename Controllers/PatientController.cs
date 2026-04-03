using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Patient_Management_System.Models;
using Patient_Management_System.Services;

namespace Patient_Management_System.Controllers
{
    [ApiController]
    [Route("api/")]
    public class PatientController(PatientService patientService) : ControllerBase
    {
        private readonly PatientService _patientService = patientService;

        [Authorize]
        [HttpGet("patients")]
        public async Task<ActionResult> GetPatients(string search = "", string sortCol = "Id", string sortDir = "asc", int pageNo = 1, int pageSize = 10)
        {
            if (!ModelState.IsValid)
            {
                return BadRequest(ModelState);
            }
            var patients = await _patientService.GetPatientsAsync(search, sortCol, sortDir, pageNo, pageSize);
            if (patients == null || !patients.Any())
            {
                return Ok("No patients found!!!");
            }
            return Ok(patients);
        }

        [Authorize]
        [HttpGet("patient/{id}")]
        public async Task<ActionResult> GetPatientById(int id)
        {
            if (!ModelState.IsValid)
            {
                return BadRequest(ModelState);
            }
            var patient = await _patientService.GetPatientByIdAsync(id);
            return Ok(patient);
        }

        [Authorize(Roles = "ADMIN")]
        [HttpPost("patient")]
        public async Task<ActionResult> CreatePatient(Patient patient)
        {
            if (!ModelState.IsValid)
            {
                return BadRequest(ModelState);
            }
            var newPatient = await _patientService.CreatePatientAsync(patient);
            return CreatedAtAction(nameof(GetPatients), new { id = newPatient.Id }, newPatient);
        }

        [Authorize(Roles = "ADMIN")]
        [HttpPut("patient/{id}")]
        public async Task<ActionResult> UpdatePatient(int id, Patient patient)
        {
            if (!ModelState.IsValid)
            {
                return BadRequest(ModelState);
            }
            var updatedPatient = await _patientService.UpdatePatientAsync(id, patient);
            return Ok(updatedPatient);
        }

        [Authorize(Roles = "ADMIN")]
        [HttpDelete("patient/{id}")]
        public async Task<ActionResult> DeletePatient(int id)
        {
            await _patientService.DeletePatientAsync(id);
            return Ok("Patient deleted successfully!!!");
        }

        [Authorize]
        [HttpPost("patient/{id}/discharge")]
        public async Task<IActionResult> DischargePatient(int id, CancellationToken cancellationToken)
        {
            var dischargeReason = Request.Form["dischargeReason"];
            if (string.IsNullOrWhiteSpace(dischargeReason))
                return BadRequest("Discharge reason is required.");

            var result = await _patientService.DischargePatientAsync(id, dischargeReason);
            return Ok(result);
        }
    }
}