namespace Patient_Management_System.Exceptions
{
    public class PatientNotFoundException(int id) : Exception($"Patient with id {id} not found!!!")
    {
    }
}